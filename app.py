import os
import base64
import tempfile

from dotenv import load_dotenv
import numpy as np
import faiss
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

load_dotenv()

app = Flask(__name__, template_folder='template', static_folder='assets')
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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


print("Cargando PDF y creando índice...")
texto = leer_pdf(RUTA_PDF)
fragmentos = dividir_texto(texto)
indice, modelo_indice = crear_indice(fragmentos)
print(f"Índice listo. {len(fragmentos)} fragmentos, {len(texto)} chars totales.")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    if 'audio' not in request.files:
        return jsonify({"error": "No se recibió audio"}), 400

    audio_file = request.files['audio']

    extension = ".webm"
    filename = audio_file.filename or ""
    if filename.endswith(".ogg"):
        extension = ".ogg"
    elif filename.endswith(".wav"):
        extension = ".wav"
    elif filename.endswith(".mp3"):
        extension = ".mp3"
    elif filename.endswith(".m4a"):
        extension = ".m4a"

    with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="es"
            )

        pregunta = transcript.text.strip()

        if not pregunta:
            return jsonify({"error": "No se detectó audio"}), 400

        contexto = buscar_fragmento(pregunta, fragmentos, indice, modelo_indice)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un asistente inmobiliario experto. Responde usando "
                        "principalmente la información del documento proporcionado. "
                        "Si no encuentras la respuesta exacta, usa tu conocimiento "
                        "para dar una respuesta útil y relevante."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Documento:\n{contexto}\n\n"
                        f"Pregunta:\n{pregunta}\n\n"
                        "Responde usando unicamente el documento anterior."
                    )
                }
            ]
        )

        respuesta = response.choices[0].message.content

        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=respuesta
        )

        audio_b64 = base64.b64encode(tts_response.content).decode('utf-8')

        return jsonify({
            "question": pregunta,
            "answer": respuesta,
            "audio": audio_b64
        })

    finally:
        os.remove(tmp_path)


if __name__ == '__main__':
    app.run(debug=True)
