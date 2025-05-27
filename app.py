import os
import json
import html
import phonenumbers
from phonenumbers import NumberParseException, is_valid_number
from flask import Flask, request, Response, jsonify, send_from_directory
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pytz import timezone
import requests

load_dotenv()
app = Flask(__name__)

ZENVIA_TOKEN = os.getenv("ZENVIA_API_TOKEN")
ZENVIA_FROM = os.getenv("ZENVIA_FROM_NUMBER")
BASE_URL = os.getenv("BASE_URL")  # ex: https://seu-app.onrender.com

CONTACTS_FILE = "contacts.json"

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def load_contacts():
    with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_contacts(data):
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def validar_numero(numero):
    try:
        return is_valid_number(phonenumbers.parse(numero, "BR"))
    except NumberParseException:
        return False

def zenvia_request(path, payload):
    url = f"https://api.zenvia.com/v2/voice/calls{path}"
    headers = {
        "Authorization": f"Bearer {ZENVIA_TOKEN}",
        "Content-Type": "application/json"
    }
    return requests.post(url, headers=headers, json=payload)

# -------------------------------------------------------------------
# Rotas de CRUD de contatos
# -------------------------------------------------------------------

@app.route("/add-contact", methods=["POST"])
def add_contact():
    data = request.get_json()
    nome = data.get("nome", "").lower()
    telefone = data.get("telefone")
    contacts = load_contacts()
    contacts[nome] = telefone
    save_contacts(contacts)
    return jsonify({"status": "sucesso", "mensagem": f"{nome} salvo com sucesso."})

@app.route("/delete-contact", methods=["POST"])
def delete_contact():
    data = request.get_json()
    nome = data.get("nome", "").lower()
    contacts = load_contacts()
    if nome in contacts:
        del contacts[nome]
        save_contacts(contacts)
        return jsonify({"status": "sucesso", "mensagem": f"{nome} removido com sucesso."})
    return jsonify({"status": "erro", "mensagem": f"{nome} não encontrado."})

@app.route("/get-contacts")
def get_contacts():
    return jsonify(load_contacts())

@app.route("/painel-contatos.html")
def serve_painel():
    return send_from_directory(".", "painel-contatos.html")

# -------------------------------------------------------------------
# Inicia a ligação de verificação
# -------------------------------------------------------------------

@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    # dispara uma ligação de verificação para o contato
    ligar_para_verificacao_por_nome(nome)
    return f"Ligação de verificação para {nome} iniciada."

def ligar_para_verificacao_por_nome(nome):
    contatos = load_contacts()
    numero = contatos.get(nome.lower())
    if numero and validar_numero(numero):
        print(f"[AGENDAMENTO] Ligando para {nome}: {numero}")
        payload = {
            "from": ZENVIA_FROM,
            "to": numero,
            "answerUrl": f"{BASE_URL}/verifica-sinal?nome={nome}"
        }
        r = zenvia_request("", payload)
        print(">> Zenvia start:", r.status_code, r.text)
    else:
        print(f"[ERRO] Contato '{nome}' não encontrado ou inválido.")

# -------------------------------------------------------------------
# Fluxo de verificação: resposta ao answerUrl do Zenvia
# -------------------------------------------------------------------

@app.route("/verifica-sinal", methods=["GET", "POST"])
def verifica_sinal():
    nome = request.args.get("nome")
    tentativa = int(request.args.get("tentativa", 1))
    # Monta resposta JSON para Zenvia callFlow
    if tentativa == 1:
        # 1ª vez diz "Central de monitoramento?" e escuta
        resp = {
            "actions": [
                {"action": "say", "options": {"text": "Central de monitoramento?"}},
                {"action": "listen", "options": {
                    "timeout": 5,
                    "endOnSilence": True,
                    "bargeIn": True,
                    "eventUrl": f"{BASE_URL}/handle-sinal?nome={nome}&tentativa=1"
                }}
            ]
        }
    else:
        # 2ª tentativa
        resp = {
            "actions": [
                {"action": "say", "options": {"text": "Contra senha incorreta. Fale novamente."}},
                {"action": "listen", "options": {
                    "timeout": 5,
                    "endOnSilence": True,
                    "bargeIn": True,
                    "eventUrl": f"{BASE_URL}/handle-sinal?nome={nome}&tentativa=2"
                }}
            ]
        }
    return jsonify(resp)

# -------------------------------------------------------------------
# Trata o evento do listen do Zenvia
# -------------------------------------------------------------------

@app.route("/handle-sinal", methods=["POST"])
def handle_sinal():
    data = request.json or {}
    texto = (data.get("speech", "") or "").lower()
    nome = request.args.get("nome")
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[RESPOSTA - Tentativa {tentativa}] {texto}")

    if "protegido" in texto:
        # sucesso
        resp = {"actions": [{"action": "say", "options": {"text": "Entendido. Obrigado."}}]}
        return jsonify(resp)

    # falha
    if tentativa < 2:
        # redireciona para /verifica-sinal com tentativa+1
        return jsonify({"redirectFlow": f"{BASE_URL}/verifica-sinal?nome={nome}&tentativa=2"})
    # 2 falhas: chama emergência
    print("[FALHA TOTAL] Chamando emergência...")
    contatos = load_contacts()
    emergencia = contatos.get("emergencia")
    if emergencia and validar_numero(emergencia):
        payload = {
            "from": ZENVIA_FROM,
            "to": emergencia,
            "answerUrl": f"{BASE_URL}/mensagem-emergencia?nome={nome}"
        }
        r = zenvia_request("", payload)
        print(">> Zenvia emergência:", r.status_code, r.text)
    # finaliza resposta imediata (Zenvia fecha a call)
    return jsonify({"actions": [{"action": "hangup"}]})

# -------------------------------------------------------------------
# Mensagem de emergência
# -------------------------------------------------------------------

@app.route("/mensagem-emergencia", methods=["GET"])
def mensagem_emergencia():
    nome = request.args.get("nome")
    # “{nome} não respondeu à verificação”
    texto = f"{nome} não respondeu à verificação"
    resp = {"actions": [{"action": "say", "options": {"text": texto}}]}
    return jsonify(resp)

# -------------------------------------------------------------------
# Agendamentos
# -------------------------------------------------------------------

scheduler = BackgroundScheduler(timezone=timezone("America/Sao_Paulo"))

@app.route("/agendar-unica", methods=["POST"])
def agendar_unica():
    data = request.get_json()
    nome = data["nome"]
    hora = int(data["hora"])
    minuto = int(data["minuto"])
    job_id = f"teste_{nome}_{hora}_{minuto}"
    scheduler.add_job(
        func=lambda n=nome: ligar_para_verificacao_por_nome(n),
        trigger="cron",
        hour=hora,
        minute=minuto,
        id=job_id,
        replace_existing=True
    )
    return jsonify({"status":"ok","mensagem":f"Ligação para {nome} agendada às {hora:02d}:{minuto:02d}"})

# exemplos fixos (você pode comentar/remover)
ligacoes = {
    "jordan": [(9,10),(9,15),(10,0),(11,0),(12,0)],
}
for nome, horarios in ligacoes.items():
    for hora, minuto in horarios:
        scheduler.add_job(
            func=lambda n=nome: ligar_para_verificacao_por_nome(n),
            trigger="cron", hour=hora, minute=minuto,
            id=f"{nome}_{hora}_{minuto}", replace_existing=True
        )

scheduler.start()

# -------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=True)
