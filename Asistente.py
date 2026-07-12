import asyncio
import os
import base64
import tempfile
import wave

from dotenv import load_dotenv
import numpy as np
import sounddevice as sd
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from openai import AsyncOpenAI

load_dotenv()

cliente = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

RATE = 24000
CHANNELS = 1
SECONDS = 5
UMBRAL_VOLUMEN = 50

RUTA_PDF = "informativo_inmobiliario.pdf"


def leer_pdf(ruta):
    reader = PdfReader(ruta)
    texto = ""

    for page in reader.pages:
        contenido = page.extract_text()
        if contenido:
            texto += contenido + "\n"

    return texto


def dividir_texto(texto, max_chars=3000):
    fragmentos = []
    inicio = 0

    while inicio < len(texto):
        fin = inicio + max_chars
        fragmentos.append(texto[inicio:fin])
        inicio += max_chars

    return fragmentos


def crear_indice(fragmentos):
    modelo_indice = SentenceTransformer("all-MiniLM-L6-v2")

    embeddings = modelo_indice.encode(fragmentos)
    embeddings = np.array(embeddings).astype("float32")

    dimension = embeddings.shape[1]

    indice_plano = faiss.IndexFlatL2(dimension)
    indice_plano.add(embeddings)

    return indice_plano, modelo_indice


def buscar_fragmento(pregunta, fragmentos, indice, modelo_indice, k=4):
    embedding_pregunta = modelo_indice.encode([pregunta])
    embedding_pregunta = np.array(embedding_pregunta).astype("float32")

    distancias, indices = indice.search(embedding_pregunta, k)

    contexto = ""

    for i in indices[0]:
        contexto += fragmentos[i] + "\n---\n"

    return contexto


def grabar_audio():
    print('Habla ahora...')
    audio = sd.rec(
        int(SECONDS * RATE),
        samplerate=RATE,
        channels=CHANNELS,
        dtype='int16'
    )
    sd.wait()

    volumen = np.abs(audio).mean()
    print('Volumen detectado', volumen)

    if volumen < UMBRAL_VOLUMEN:
        return None

    return audio.tobytes()


async def transcribir_audio(audio_bytes):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
        ruta_audio = temp.name

    with wave.open(ruta_audio, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(audio_bytes)

    with open(ruta_audio, "rb") as f:
        transcripcion = await cliente.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=f,
            language="es"
        )

    os.remove(ruta_audio)

    return transcripcion.text


def reproducirAudio(audio_bytes):
    if len(audio_bytes) == 0:
        print("No se recibio audio de respuesta")
        return

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)

    sd.play(audio_np, samplerate=RATE)
    sd.wait()


async def main():
    print('Paso 1...Leer PDF')
    texto = leer_pdf(RUTA_PDF)
    print('Paso 2...Dividir Texto')
    fragmentos = dividir_texto(texto)
    print('Paso 3...Crear indices')
    indice, modelo_indice = crear_indice(fragmentos)
    print('Listo. Iniciando asistente de voz...\n')

    async with cliente.realtime.connect(model="gpt-realtime") as conn:

        await conn.session.update(
            session={
                "type": "realtime",
                "instructions": (
                    "Eres un asistente de voz que responde preguntas basandote "
                    "UNICAMENTE en el documento que se te proporciona en cada mensaje. "
                    "Si la respuesta no aparece en el documento, responde exactamente: "
                    "'No encontre esa informacion en mi base de datos.'"
                ),
                "audio": {
                    "output": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": RATE,
                        },
                        "voice": "alloy",
                    },
                },
            }
        )

        while True:
            comando = input('\nPresiona ENTER para hablar o escribe salir: ')

            if comando.lower() in ['salir']:
                break

            audio_bytes = grabar_audio()

            if audio_bytes is None:
                print('No se detecto suficiente volumen, intenta de nuevo')
                continue

            pregunta = await transcribir_audio(audio_bytes)

            if not pregunta.strip():
                print('No se detecto una pregunta')
                continue

            print('\nTu: ', pregunta)

            contexto = buscar_fragmento(pregunta, fragmentos, indice, modelo_indice)

            mensaje_con_contexto = f"""Documento:
{contexto}

Pregunta:
{pregunta}

Responde usando unicamente el documento anterior."""

            await conn.conversation.item.create(item={
                'type': 'message',
                'role': 'user',
                'content': [{
                    'type': 'input_text',
                    'text': mensaje_con_contexto
                }]
            })

            await conn.response.create(response={
                'output_modalities': ['audio']
            })

            print('Asistente: ', end='', flush=True)

            audio_respuesta = bytearray()

            async for event in conn:

                if event.type == 'response.output_text.delta':
                    print(event.delta, end='', flush=True)

                if event.type == 'response.output_audio.delta':
                    audio_respuesta.extend(base64.b64decode(event.delta))

                if event.type == 'response.done':
                    break

                if event.type == 'error':
                    print('Error: ', event)
                    break

            reproducirAudio(bytes(audio_respuesta))


if __name__ == '__main__':
    asyncio.run(main())