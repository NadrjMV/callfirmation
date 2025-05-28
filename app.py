import os
import json
import html
import phonenumbers
from phonenumbers import NumberParseException, is_valid_number
from flask import Flask, request, Response, jsonify, send_from_directory
from signalwire.rest import Client as SignalWireClient
from signalwire.voice_response import VoiceResponse
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pytz import timezone

load_dotenv()
app = Flask(__name__)

signalwire_project = os.getenv("SIGNALWIRE_PROJECT")
signalwire_token = os.getenv("SIGNALWIRE_TOKEN")
signalwire_space = os.getenv("SIGNALWIRE_SPACE_URL")  # exemplo: example.signalwire.com
signalwire_number = os.getenv("SIGNALWIRE_NUMBER")  # Pode manter o nome da variável se for o mesmo número
client = SignalWireClient(signalwire_project, signalwire_token, signalwire_space_url=signalwire_space)

CONTACTS_FILE = "contacts.json"
base_url = os.getenv("BASE_URL", "http://localhost:5000")

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
    else:
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
        return _twiml_response("Entendido. Obrigado.", voice="alice")

    if tentativa < 2:
        print("[TENTATIVA FALHOU] Repetindo verificação...")
        resp = VoiceResponse()

        # Usando <Record> para captura de voz, gravação e reconhecimento depois
        record_action_url = f"{base_url}/verifica-sinal?tentativa={tentativa + 1}"
        resp.say("Contra senha incorreta. Fale novamente.", language="pt-BR", voice="alice")
        resp.record(
            action=record_action_url,
            method="POST",
            max_length=5,
            play_beep=True,
            timeout=5,
            transcribe=True,
            transcribe_callback=record_action_url,
            trim="trim-silence",
            recording_status_callback=record_action_url,
            recording_status_callback_method="POST",
            language="pt-BR"
        )
        return Response(str(resp), mimetype="text/xml")

    print("[FALHA TOTAL] Chamando número de emergência...")
    contatos = load_contacts()
    numero_emergencia = contatos.get("emergencia")

    numero_falhou = request.values.get("To", None)
    nome_falhou = None
    if numero_falhou:
        for nome, tel in contatos.items():
            if tel == numero_falhou:
                nome_falhou = nome
                break

    print(f"[DEBUG] Número que falhou: {numero_falhou}")
    print(f"[DEBUG] Nome correspondente: {nome_falhou}")
    print(f"[DEBUG] Número emergência: {numero_emergencia}")

    if numero_emergencia and validar_numero(numero_emergencia):
        ligar_para_emergencia(
            numero_destino=numero_emergencia,
            origem_falha_numero=numero_falhou,
            origem_falha_nome=nome_falhou
        )
        return _twiml_response("Falha na confirmação. Chamando responsáveis.", voice="alice")
    else:
        print("[ERRO] Número de emergência não encontrado ou inválido.")
        return _twiml_response("Erro ao tentar contatar emergência. Verifique os números cadastrados.", voice="alice")

def ligar_para_verificacao(numero_destino):
    full_url = f"{base_url}/verifica-sinal?tentativa=1"
    response = VoiceResponse()

    response.say("Central de monitoramento?", language="pt-BR", voice="alice")
    response.record(
        action=full_url,
        method="POST",
        max_length=5,
        play_beep=True,
        timeout=5,
        transcribe=True,
        transcribe_callback=full_url,
        trim="trim-silence",
        recording_status_callback=full_url,
        recording_status_callback_method="POST",
        language="pt-BR"
    )

    client.calls.create(
        to=numero_destino,
        from_=signalwire_number,
        twiml=str(response)
    )

def validar_numero(numero):
    try:
        parsed = phonenumbers.parse(numero, "BR")
        return is_valid_number(parsed)
    except NumberParseException:
        return False

def ligar_para_emergencia(numero_destino, origem_falha_numero=None, origem_falha_nome=None):
    if origem_falha_nome:
        mensagem = f"Alerta de verificação de segurança. {origem_falha_nome} não respondeu à verificação de segurança. Por favor, confirme dizendo OK ou Entendido."
    elif origem_falha_numero:
        mensagem = f"O número {origem_falha_numero} não respondeu à verificação de segurança. Por favor, confirme dizendo OK ou Entendido."
    else:
        mensagem = "Alguém não respondeu à verificação de segurança. Por favor, confirme dizendo OK ou Entendido."

    full_url = f"{base_url}/verifica-emergencia?tentativa=1"
    response = VoiceResponse()

    response.say(mensagem, language="pt-BR", voice="alice")
    response.record(
        action=full_url,
        method="POST",
        max_length=5,
        play_beep=True,
        timeout=5,
        transcribe=True,
        transcribe_callback=full_url,
        trim="trim-silence",
        recording_status_callback=full_url,
        recording_status_callback_method="POST",
        language="pt-BR"
    )

    client.calls.create(
        to=numero_destino,
        from_=signalwire_number,
        twiml=str(response)
    )

@app.route("/verifica-emergencia", methods=["POST"])
def verifica_emergencia():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[RESPOSTA EMERGENCIA - Tentativa {tentativa}] {resposta}")

    confirmacoes = ["ok", "confirma", "entendido", "entendi", "obrigado", "valeu"]

    if any(palavra in resposta for palavra in confirmacoes):
        print("Confirmação recebida do chefe.")
        return _twiml_response("Confirmação recebida. Obrigado.", voice="alice")

    if tentativa < 3:
        print("Sem confirmação. Repetindo mensagem...")
        resp = VoiceResponse()

        resp.say("Alerta de verificação de segurança. Por favor, confirme dizendo OK ou Entendido.", language="pt-BR", voice="alice")
        full_url = f"{base_url}/verifica-emergencia?tentativa={tentativa + 1}"
        resp.record(
            action=full_url,
            method="POST",
            max_length=5,
            play_beep=True,
            timeout=5,
            transcribe=True,
            transcribe_callback=full_url,
            trim="trim-silence",
            recording_status_callback=full_url,
            recording_status_callback_method="POST",
            language="pt-BR"
        )
        return Response(str(resp), mimetype="text/xml")

    print("Nenhuma confirmação após múltiplas tentativas.")
    return _twiml_response("Nenhuma confirmação recebida. Encerrando a chamada.", voice="alice")

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
        print(f"[ERRO] Contato '{nome}' não encontrado ou número inválido.")

def _twiml_response(text, voice="alice"):
    resp = VoiceResponse()
    resp.say(text, voice=voice, language="pt-BR")
    return Response(str(resp), mimetype="text/xml")

def agendar_ligacoes():
    contatos = load_contacts()
    for nome, numero in contatos.items():
        if nome.lower() != "emergencia" and validar_numero(numero):
            ligar_para_verificacao(numero)

def agendar_multiplas_ligacoes():
    agendamentos = [
        {"nome": "jordan", "hora": 8, "minuto": 44},
        {"nome": "jordan", "hora": 8, "minuto": 45},
    ]

    for item in agendamentos:
        job_id = f"{item['nome']}_{item['hora']:02d}_{item['minuto']:02d}"
        scheduler.add_job(
            func=lambda nome=item["nome"]: ligar_para_verificacao_por_nome(nome),
            trigger="cron",
            hour=item["hora"],
            minute=item["minuto"],
            id=job_id,
            replace_existing=True
        )

# Ativa o agendamento na inicialização do app
agendar_multiplas_ligacoes()
scheduler.start()

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(agendar_ligacoes, 'interval', hours=24)  # Ajuste a frequência como desejar
    scheduler.start()
    app.run(host="0.0.0.0", port=5000, debug=True)

#created by Jordanlvs 💼, all rights reserved ® 
