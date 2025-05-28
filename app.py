import os
import json
import phonenumbers
from phonenumbers import NumberParseException, is_valid_number
from flask import Flask, request, Response, jsonify, send_from_directory
from signalwire.rest import Client as SignalWireClient
from signalwire.voice_response import VoiceResponse
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
 
load_dotenv()
app = Flask(__name__)

# Variáveis do ambiente — configure corretamente no seu .env
signalwire_project = os.getenv("SIGNALWIRE_PROJECT")
signalwire_token = os.getenv("SIGNALWIRE_TOKEN")
signalwire_space = os.getenv("SIGNALWIRE_SPACE_URL")  # ex: example.signalwire.com (sem https://)
signalwire_number = os.getenv("SIGNALWIRE_NUMBER")  # seu número comprado no SignalWire, ex: +15017122661
base_url = os.getenv("BASE_URL", "http://localhost:5000")

client = SignalWireClient(signalwire_project, signalwire_token, signalwire_space)

CONTACTS_FILE = "contacts.json"
scheduler = BackgroundScheduler()
scheduler.start()

def load_contacts():
    try:
        with open(CONTACTS_FILE, "r") as f:
            contatos = json.load(f)
        print("Contatos carregados com sucesso.")
        return contatos
    except Exception as e:
        print(f"Erro ao carregar contatos: {e}")
        return {}

def save_contacts(data):
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def validar_numero(numero):
    try:
        parsed = phonenumbers.parse(numero, None)
        return is_valid_number(parsed)
    except NumberParseException:
        return False

def _twiml_response(text, voice="alice"):
    resp = VoiceResponse()
    resp.say(text, voice=voice, language="pt-BR")
    return Response(str(resp), mimetype="text/xml")

@app.route("/add-contact", methods=["POST"])
def add_contact():
    data = request.get_json()
    nome = data.get("nome", "").lower().strip()
    telefone = data.get("telefone")
    if not nome or not telefone:
        return jsonify({"status": "erro", "mensagem": "Nome e telefone são obrigatórios."}), 400
    if not validar_numero(telefone):
        return jsonify({"status": "erro", "mensagem": "Número inválido."}), 400
    contacts = load_contacts()
    contacts[nome] = telefone
    save_contacts(contacts)
    return jsonify({"status": "sucesso", "mensagem": f"{nome} salvo com sucesso."})

@app.route("/delete-contact", methods=["POST"])
def delete_contact():
    data = request.get_json()
    nome = data.get("nome", "").lower().strip()
    contacts = load_contacts()
    if nome in contacts:
        del contacts[nome]
        save_contacts(contacts)
        return jsonify({"status": "sucesso", "mensagem": f"{nome} removido com sucesso."})
    return jsonify({"status": "erro", "mensagem": f"{nome} não encontrado."}), 404

@app.route("/get-contacts")
def get_contacts():
    return jsonify(load_contacts())

@app.route("/listar_contatos")
def listar_contatos():
    return jsonify(load_contacts())

@app.route("/painel-contatos.html")
def serve_painel():
    return send_from_directory(".", "painel-contatos.html")

def ligar_para_verificacao(numero_destino):
    if not validar_numero(numero_destino):
        print(f"[ERRO] Número inválido: {numero_destino}")
        return None

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
    try:
        chamada = client.calls.create(
            to=numero_destino,
            from_=signalwire_number,
            twiml=str(response)
        )
        print(f"Chamada criada para {numero_destino}, SID: {chamada.sid}")
        return chamada.sid
    except Exception as e:
        print(f"Erro ao criar chamada para {numero_destino}: {e}")
        return None

def ligar_para_verificacao_por_nome(nome):
    contatos = load_contacts()
    numero = contatos.get(nome.lower())
    if numero and validar_numero(numero):
        return ligar_para_verificacao(numero)
    print(f"[ERRO] Contato '{nome}' não encontrado ou número inválido.")
    return None

@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    sid = ligar_para_verificacao_por_nome(nome)
    if sid:
        return f"Ligação de verificação para {nome} iniciada. SID: {sid}"
    return f"Erro ao iniciar ligação para {nome}.", 400

@app.route("/forcar_ligacao/<nome>", methods=["GET"])
def forcar_ligacao(nome):
    if not nome:
        print("[ERRO] Nome do contato não foi fornecido na URL.")
        return jsonify({"status": "erro", "mensagem": "Nome do contato é obrigatório."}), 400

    print(f"[INFO] Requisição recebida para forçar ligação para: {nome}")
    contatos = load_contacts()

    if nome.lower() not in contatos:
        print(f"[ERRO] Contato '{nome}' não encontrado na lista.")
        return jsonify({"status": "erro", "mensagem": f"Contato '{nome}' não encontrado."}), 404

    numero = contatos[nome.lower()]
    if not validar_numero(numero):
        print(f"[ERRO] Número inválido para o contato '{nome}': {numero}")
        return jsonify({"status": "erro", "mensagem": f"Número inválido para '{nome}'."}), 400

    sid = ligar_para_verificacao(numero)
    if sid:
        print(f"[SUCESSO] Ligação forçada para {nome} iniciada. SID: {sid}")
        return jsonify({"status": "sucesso", "mensagem": f"Ligação para {nome} iniciada com sucesso.", "sid": sid})
    else:
        print(f"[ERRO] Falha ao iniciar ligação para {nome}.")
        return jsonify({"status": "erro", "mensagem": f"Falha ao iniciar ligação para {nome}."}), 500

@app.route("/verifica-sinal", methods=["POST"])
def verifica_sinal():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[RESPOSTA - Tentativa {tentativa}] {resposta}")

    if "protegido" in resposta:
        return _twiml_response("Entendido. Obrigado.", voice="alice")

    if tentativa < 2:
        resp = VoiceResponse()
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

    contatos = load_contacts()
    numero_emergencia = contatos.get("emergencia")
    if numero_emergencia and validar_numero(numero_emergencia):
        ligar_para_emergencia(numero_emergencia)
        return _twiml_response("Falha na confirmação. Chamando responsáveis.", voice="alice")
    return _twiml_response("Erro ao tentar contatar emergência.", voice="alice")

def ligar_para_emergencia(numero_destino):
    mensagem = "Alerta. Não houve resposta à verificação. Diga OK para confirmar."
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
    try:
        chamada = client.calls.create(
            to=numero_destino,
            from_=signalwire_number,
            twiml=str(response)
        )
        print(f"Chamada de emergência criada para {numero_destino}, SID: {chamada.sid}")
        return chamada.sid
    except Exception as e:
        print(f"Erro ao criar chamada de emergência: {e}")
        return None

@app.route("/verifica-emergencia", methods=["POST"])
def verifica_emergencia():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    confirmacoes = ["ok", "confirma", "entendido", "entendi", "obrigado", "valeu"]

    if any(p in resposta for p in confirmacoes):
        return _twiml_response("Confirmação recebida. Obrigado.", voice="alice")

    if tentativa < 3:
        resp = VoiceResponse()
        resp.say("Alerta. Por favor, confirme dizendo OK ou Entendido.", language="pt-BR", voice="alice")
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

    return _twiml_response("Nenhuma confirmação recebida. Encerrando a chamada.", voice="alice")

def agendar_multiplas_ligacoes():
    agendamentos = [
        {"nome": "jordan", "hora": 10, "minuto": 34},
        {"nome": "jordan", "hora": 10, "minuto": 37},
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
        print(f"Agendamento criado para {item['nome']} às {item['hora']:02d}:{item['minuto']:02d}")

if __name__ == "__main__":
    agendar_multiplas_ligacoes()
    app.run(host="0.0.0.0", port=5000, debug=True)

# created by Jordanlvs 💼, all rights reserved ®
