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
from signalwire.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather  # SignalWire também usa TwiML

load_dotenv()
app = Flask(__name__)

# SignalWire
signalwire_project = os.getenv("SIGNALWIRE_PROJECT")
signalwire_token = os.getenv("SIGNALWIRE_TOKEN")
signalwire_space = os.getenv("SIGNALWIRE_SPACE_URL")  # ex: example.signalwire.com
base_url = os.getenv("BASE_URL")
signalwire_number = os.getenv("SIGNALWIRE_NUMBER")

client = Client(signalwire_project, signalwire_token)
client.api.base_url = f"https://sunshield.signalwire.com"

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
        return _twiml_response("Entendido. Obrigado.", voice="br-PT-Wavenet-A")

    if tentativa < 2:
        print("[TENTATIVA FALHOU] Repetindo verificação...")
        resp = VoiceResponse()
        gather = Gather(
            input="speech",
            timeout=5,
            speechTimeout="auto",
            action=f"{base_url}/verifica-sinal?tentativa={tentativa + 1}",
            method="POST",
            language="pt-BR"
        )
        gather.say("Contra senha incorreta. Fale novamente.", language="pt-BR", voice="br-PT-Wavenet-A")
        resp.append(gather)
        resp.redirect(f"{base_url}/verifica-sinal?tentativa={tentativa + 1}", method="POST")
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

    if numero_emergencia and validar_numero(numero_emergencia):
        ligar_para_emergencia(numero_emergencia, numero_falhou, nome_falhou)
        return _twiml_response("Falha na confirmação. Chamando responsáveis.", voice="br-PT-Wavenet-A")
    else:
        return _twiml_response("Erro ao tentar contatar emergência. Verifique os números cadastrados.", voice="br-PT-Wavenet-A")

def ligar_para_verificacao(numero_destino):
    full_url = f"{base_url}/verifica-sinal?tentativa=1"
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=5,
        speechTimeout="auto",
        action=full_url,
        method="POST",
        language="pt-BR"
    )
    gather.say("Central de monitoramento?", language="pt-BR", voice="br-PT-Wavenet-A")
    response.append(gather)
    response.redirect(full_url, method="POST")

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
        mensagem = f"Alerta de verificação de segurança. {origem_falha_nome} não respondeu à verificação. Confirme dizendo OK ou Entendido."
    elif origem_falha_numero:
        mensagem = f"O número {origem_falha_numero} não respondeu à verificação. Confirme dizendo OK ou Entendido."
    else:
        mensagem = "Alguém não respondeu à verificação de segurança. Confirme dizendo OK ou Entendido."

    full_url = f"{base_url}/verifica-emergencia?tentativa=1"
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        timeout=5,
        speechTimeout="auto",
        action=full_url,
        method="POST",
        language="pt-BR"
    )
    gather.say(mensagem, language="pt-BR", voice="br-PT-Wavenet-A")
    response.append(gather)
    response.redirect(full_url, method="POST")

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
        return _twiml_response("Confirmação recebida. Obrigado.", voice="br-PT-Wavenet-A")

    if tentativa < 3:
        resp = VoiceResponse()
        gather = Gather(
            input="speech",
            timeout=5,
            speechTimeout="auto",
            action=f"{base_url}/verifica-emergencia?tentativa={tentativa + 1}",
            method="POST",
            language="pt-BR"
        )
        gather.say("Alerta de verificação de segurança. Confirme dizendo OK ou Entendido.", language="pt-BR", voice="br-PT-Wavenet-A")
        resp.append(gather)
        resp.redirect(f"{base_url}/verifica-emergencia?tentativa={tentativa + 1}", method="POST")
        return Response(str(resp), mimetype="text/xml")

    return _twiml_response("Nenhuma confirmação recebida. Encerrando a chamada.", voice="br-PT-Wavenet-A")

@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    ligar_para_verificacao_por_nome(nome)
    return f"Ligação de verificação para {nome} iniciada."

def ligar_para_verificacao_por_nome(nome):
    contatos = load_contacts()
    numero = contatos.get(nome.lower())
    if numero and validar_numero(numero):
        ligar_para_verificacao(numero)

def _twiml_response(texto, voice="br-PT-Wavenet-A"):
    resp = VoiceResponse()
    resp.say(texto, language="pt-BR", voice=voice)
    return Response(str(resp), mimetype="text/xml")

scheduler = BackgroundScheduler(timezone=timezone("America/Sao_Paulo"))

@app.route("/forcar_ligacao/<nome>")
def forcar_ligacao(nome):
    ligar_para_verificacao_por_nome(nome)
    return f"Ligação forçada para {nome}"

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

    return jsonify({"status": "ok", "mensagem": f"Ligação para {nome} agendada às {hora:02d}:{minuto:02d}"})

def agendar_multiplas_ligacoes():
    agendamentos = [
        {"nome": "jordan", "hora": datetime.now().hour, "minuto": (datetime.now().minute + 1) % 60},
    ]
    for ag in agendamentos:
        scheduler.add_job(
            func=lambda nome=ag["nome"]: ligar_para_verificacao_por_nome(nome),
            trigger="cron",
            hour=ag["hora"],
            minute=ag["minuto"],
            id=f"verificacao_{ag['nome']}",
            replace_existing=True
        )

def agendar_ligacoes_fixas():
    ligacoes = [
        {"nome": "jordan", "hora": 11, "minuto": 10},
    ]
    for item in ligacoes:
        scheduler.add_job(
            func=lambda nome=item["nome"]: ligar_para_verificacao_por_nome(nome),
            trigger="cron",
            hour=item["hora"],
            minute=item["minuto"],
            id=f"fixo_{item['nome']}",
            replace_existing=True
        )

scheduler.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

#created by Jordanlvs 💼, all rights reserved ® 
