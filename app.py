# app.py
import os
import json
import html
import phonenumbers
from phonenumbers import NumberParseException, is_valid_number
from flask import Flask, request, Response, jsonify, send_from_directory
from plivo import RestClient
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pytz import timezone

load_dotenv()
app = Flask(__name__)

plivo_auth_id = os.getenv("PLIVO_AUTH_ID")
plivo_auth_token = os.getenv("PLIVO_AUTH_TOKEN")
plivo_number = os.getenv("PLIVO_NUMBER")
base_url = os.getenv("BASE_URL")
client = RestClient(plivo_auth_id, plivo_auth_token)

CONTACTS_FILE = "contacts.json"

def load_contacts():
    with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_contacts(data):
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

@app.route("/verifica-sinal", methods=["GET", "POST"])
def verifica_sinal():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[RESPOSTA - Tentativa {tentativa}] {resposta}")

    if "protegido" in resposta:
        print("[SUCESSO] Palavra correta detectada.")
        return _plivo_response("Entendido. Obrigado.")

    if tentativa < 2:
        print("[TENTATIVA FALHOU] Repetindo verificação...")
        return _plivo_gather_response("Contra senha incorreta. Fale novamente.", tentativa + 1)

    print("[FALHA TOTAL] Chamando número de emergência...")
    contatos = load_contacts()
    numero_emergencia = contatos.get("emergencia")
    numero_falhou = request.values.get("To", None)
    nome_falhou = next((nome for nome, tel in contatos.items() if tel == numero_falhou), None)

    if numero_emergencia and validar_numero(numero_emergencia):
        ligar_para_emergencia(numero_emergencia, numero_falhou, nome_falhou)
        return _plivo_response("Falha na confirmação. Chamando responsáveis.")
    return _plivo_response("Erro ao tentar contatar emergência.")

def ligar_para_verificacao(numero_destino):
    client.calls.create(
        from_=plivo_number,
        to=numero_destino,
        answer_url=f"{base_url}/verifica-sinal?tentativa=1",
        answer_method="POST"
    )

def validar_numero(numero):
    try:
        return is_valid_number(phonenumbers.parse(numero, "BR"))
    except NumberParseException:
        return False

def ligar_para_emergencia(numero_destino, origem_falha_numero=None, origem_falha_nome=None):
    if origem_falha_nome:
        mensagem = f"Alerta de verificação de segurança. {origem_falha_nome} não respondeu à verificação. Por favor, entre em contato."
    elif origem_falha_numero:
        mensagem = f"O número {origem_falha_numero} não respondeu à verificação. Por favor, entre em contato."
    else:
        mensagem = "Alguém não respondeu à verificação de segurança."

    client.calls.create(
        from_=plivo_number,
        to=numero_destino,
        answer_url=f"{base_url}/mensagem-emergencia?msg={html.escape(mensagem)}",
        answer_method="GET"
    )

@app.route("/mensagem-emergencia")
def mensagem_emergencia():
    msg = request.args.get("msg", "Alerta. Falha de verificação.")
    return _plivo_response(msg + " Encerrando ligação.")

@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    ligar_para_verificacao_por_nome(nome)
    return f"Ligação de verificação para {nome} iniciada."

def ligar_para_verificacao_por_nome(nome):
    contatos = load_contacts()
    numero = contatos.get(nome.lower())
    if numero and validar_numero(numero):
        print(f"[AGENDAMENTO] Ligando para {nome}: {numero}")
        ligar_para_verificacao(numero)
    else:
        print(f"[ERRO] Contato '{nome}' inválido ou não encontrado.")

def _plivo_response(texto):
    return Response(f"""
        <Response>
            <Speak language="pt-BR" voice="WOMAN">{html.escape(texto)}</Speak>
        </Response>
    """, mimetype="text/xml")

def _plivo_gather_response(texto, tentativa):
    return Response(f"""
        <Response>
            <GetInput action="{base_url}/verifica-sinal?tentativa={tentativa}" method="POST" inputType="speech" language="pt-BR" speechEndTimeout="auto">
                <Speak language="pt-BR" voice="WOMAN">{html.escape(texto)}</Speak>
            </GetInput>
        </Response>
    """, mimetype="text/xml")

@app.route("/agendar-unica", methods=["POST"])
def agendar_unica():
    data = request.get_json()
    nome = data.get("nome")
    hora = int(data.get("hora"))
    minuto = int(data.get("minuto"))

    job_id = f"teste_{nome}_{hora}_{minuto}"
    scheduler.add_job(
        func=lambda: ligar_para_verificacao_por_nome(nome),
        trigger="cron",
        hour=hora,
        minute=minuto,
        id=job_id,
        replace_existing=True
    )
    return jsonify({"status": "ok", "mensagem": f"Ligação para {nome} agendada às {hora:02d}:{minuto:02d}."})

# ⏰ Agendamentos
scheduler = BackgroundScheduler(timezone=timezone("America/Sao_Paulo"))

ligacoes = {
    "gustavo": [(10, 11), (11, 0), (12, 0)],
    "verificacao1": [(10, 30), (10, 34)]
}
for nome, horarios in ligacoes.items():
    for hora, minuto in horarios:
        scheduler.add_job(
            func=lambda nome=nome: ligar_para_verificacao_por_nome(nome),
            trigger="cron",
            hour=hora,
            minute=minuto,
            id=f"{nome}_{hora}_{minuto}",
            replace_existing=True
        )

scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
