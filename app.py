import os
import json
import phonenumbers
import traceback
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

print(f"[INIT] Project: {signalwire_project}")
print(f"[INIT] Token: {signalwire_token[:5]}...")  
print(f"[INIT] Space URL: {signalwire_space}")
print(f"[INIT] SignalWire Number: {signalwire_number}")
print(f"[INIT] Base URL: {base_url}")

client = SignalWireClient(signalwire_project, signalwire_token, signalwire_space)

CONTACTS_FILE = "contacts.json"
scheduler = BackgroundScheduler()
scheduler.start()

def load_contacts():
    try:
        with open(CONTACTS_FILE, "r") as f:
            contatos = json.load(f)
        print(f"[LOAD_CONTACTS] Contatos carregados com sucesso: {len(contatos)} contatos.")
        return contatos
    except FileNotFoundError:
        print(f"[LOAD_CONTACTS] Arquivo {CONTACTS_FILE} não encontrado. Retornando dicionário vazio.")
        return {}
    except json.JSONDecodeError as e:
        print(f"[LOAD_CONTACTS] Erro ao decodificar JSON: {e}")
        return {}
    except Exception as e:
        print(f"[LOAD_CONTACTS] Erro inesperado ao carregar contatos: {e}")
        return {}

def save_contacts(data):
    try:
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SAVE_CONTACTS] Contatos salvos com sucesso. Total contatos: {len(data)}")
    except Exception as e:
        print(f"[SAVE_CONTACTS] Erro ao salvar contatos: {e}")

def validar_numero(numero):
    try:
        parsed = phonenumbers.parse(numero, None)
        valido = is_valid_number(parsed)
        print(f"[VALIDAR_NUMERO] Número '{numero}' válido? {valido}")
        return valido
    except NumberParseException as e:
        print(f"[VALIDAR_NUMERO] Exceção ao validar número '{numero}': {e}")
        return False

def _twiml_response(text, voice="alice"):
    resp = VoiceResponse()
    resp.say(text, voice=voice, language="pt-BR")
    print(f"[TWIML_RESPONSE] Resposta gerada com texto: '{text}'")
    return Response(str(resp), mimetype="text/xml")

@app.route("/add-contact", methods=["POST"])
def add_contact():
    data = request.get_json()
    print(f"[ADD_CONTACT] Dados recebidos: {data}")
    nome = data.get("nome", "").lower().strip()
    telefone = data.get("telefone")
    if not nome or not telefone:
        print(f"[ADD_CONTACT] Erro: Nome ou telefone faltando.")
        return jsonify({"status": "erro", "mensagem": "Nome e telefone são obrigatórios."}), 400
    if not validar_numero(telefone):
        print(f"[ADD_CONTACT] Erro: Número inválido '{telefone}'.")
        return jsonify({"status": "erro", "mensagem": "Número inválido."}), 400
    contacts = load_contacts()
    contacts[nome] = telefone
    save_contacts(contacts)
    print(f"[ADD_CONTACT] Contato '{nome}' salvo com telefone '{telefone}'.")
    return jsonify({"status": "sucesso", "mensagem": f"{nome} salvo com sucesso."})

@app.route("/delete-contact", methods=["POST"])
def delete_contact():
    data = request.get_json()
    print(f"[DELETE_CONTACT] Dados recebidos: {data}")
    nome = data.get("nome", "").lower().strip()
    contacts = load_contacts()
    if nome in contacts:
        del contacts[nome]
        save_contacts(contacts)
        print(f"[DELETE_CONTACT] Contato '{nome}' removido.")
        return jsonify({"status": "sucesso", "mensagem": f"{nome} removido com sucesso."})
    print(f"[DELETE_CONTACT] Contato '{nome}' não encontrado.")
    return jsonify({"status": "erro", "mensagem": f"{nome} não encontrado."}), 404

@app.route("/get-contacts")
def get_contacts():
    contacts = load_contacts()
    print(f"[GET_CONTACTS] Retornando {len(contacts)} contatos.")
    return jsonify(contacts)

@app.route("/listar_contatos")
def listar_contatos():
    contacts = load_contacts()
    print(f"[LISTAR_CONTATOS] Retornando {len(contacts)} contatos.")
    return jsonify(contacts)

@app.route("/painel-contatos.html")
def serve_painel():
    print(f"[SERVE_PAINEL] Enviando painel-contatos.html")
    return send_from_directory(".", "painel-contatos.html")

def ligar_para_verificacao(numero_destino):
    print(f"[LIGAR_PARA_VERIFICACAO] Tentando ligar para: {numero_destino}")
    if not validar_numero(numero_destino):
        print(f"[LIGAR_PARA_VERIFICACAO] Número inválido: {numero_destino}")
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
        print(f"[LIGAR_PARA_VERIFICACAO] Chamada criada para {numero_destino}, SID: {chamada.sid}")
        return chamada.sid
    except Exception as e:
        print(f"[LIGAR_PARA_VERIFICACAO] Erro ao criar chamada para {numero_destino}: {e}")
        return None

def ligar_para_verificacao_por_nome(nome):
    print(f"[LIGAR_PARA_VERIFICACAO_POR_NOME] Ligando para o contato '{nome}'.")
    contatos = load_contacts()
    numero = contatos.get(nome.lower())
    if numero and validar_numero(numero):
        return ligar_para_verificacao(numero)
    print(f"[LIGAR_PARA_VERIFICACAO_POR_NOME] Contato '{nome}' não encontrado ou número inválido.")
    return None

@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    print(f"[TESTAR_VERIFICACAO] Requisição para testar verificação do contato: {nome}")
    sid = ligar_para_verificacao_por_nome(nome)
    if sid:
        print(f"[TESTAR_VERIFICACAO] Ligação iniciada para {nome} com SID: {sid}")
        return f"Ligação de verificação para {nome} iniciada. SID: {sid}"
    print(f"[TESTAR_VERIFICACAO] Erro ao iniciar ligação para {nome}.")
    return f"Erro ao iniciar ligação para {nome}.", 400

@app.route("/forcar_ligacao/<nome>", methods=["GET"])
def forcar_ligacao(nome):
    try:
        print(f"Tentando iniciar ligação para: {nome}")
        sid = ligar_para_verificacao_por_nome(nome)  # sua função
        if sid:
            return jsonify({"mensagem": f"Ligação iniciada para {nome}.", "status": "ok"})
        else:
            return jsonify({"mensagem": f"Falha ao iniciar ligação para {nome}.", "status": "erro"}), 500
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({
            "mensagem": "Erro interno do servidor.",
            "status": "erro",
            "detalhes": str(e),
            "traceback": tb
        }), 500

@app.route("/verifica-sinal", methods=["POST"])
def verifica_sinal():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[VERIFICA_SINAL] Resposta recebida - Tentativa {tentativa}: '{resposta}'")

    if "protegido" in resposta:
        print("[VERIFICA_SINAL] Palavra-chave 'protegido' detectada. Finalizando com sucesso.")
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
        print(f"[VERIFICA_SINAL] Tentativa {tentativa} falhou, solicitando nova gravação.")
        return Response(str(resp), mimetype="text/xml")

    contatos = load_contacts()
    numero_emergencia = contatos.get("emergencia")
    if numero_emergencia and validar_numero(numero_emergencia):
        print("[VERIFICA_SINAL] Falha na verificação, chamando emergência.")
        ligar_para_emergencia(numero_emergencia)
        return _twiml_response("Falha na confirmação. Chamando responsáveis.", voice="alice")

    print("[VERIFICA_SINAL] Não foi possível chamar emergência - número inválido ou não definido.")
    return _twiml_response("Erro ao tentar contatar emergência.", voice="alice")

def ligar_para_emergencia(numero_destino):
    print(f"[LIGAR_PARA_EMERGENCIA] Ligando para emergência no número {numero_destino}")
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
        print(f"[LIGAR_PARA_EMERGENCIA] Chamada de emergência criada, SID: {chamada.sid}")
        return chamada.sid
    except Exception as e:
        print(f"[LIGAR_PARA_EMERGENCIA] Erro ao criar chamada de emergência: {e}")
        return None

@app.route("/verifica-emergencia", methods=["POST"])
def verifica_emergencia():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[VERIFICA_EMERGENCIA] Resposta emergência - Tentativa {tentativa}: '{resposta}'")

    if "ok" in resposta:
        print("[VERIFICA_EMERGENCIA] Emergência confirmada com OK. Finalizando.")
        return _twiml_response("Confirmação recebida. Obrigado.", voice="alice")

    if tentativa < 2:
        resp = VoiceResponse()
        record_action_url = f"{base_url}/verifica-emergencia?tentativa={tentativa + 1}"
        resp.say("Não entendi. Por favor, diga OK para confirmar.", language="pt-BR", voice="alice")
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
        print(f"[VERIFICA_EMERGENCIA] Tentativa {tentativa} falhou, solicitando nova gravação.")
        return Response(str(resp), mimetype="text/xml")

    print("[VERIFICA_EMERGENCIA] Não foi possível confirmar emergência após tentativas.")
    return _twiml_response("Não foi possível confirmar a emergência. Encerrando.", voice="alice")

# Scheduler exemplo para teste de chamadas periódicas, opcional
def job_teste():
    print("[SCHEDULER] Executando job de teste.")
    ligar_para_verificacao_por_nome("emergencia")

scheduler.add_job(job_teste, 'interval', minutes=60)

if __name__ == "__main__":
    print("[APP] Iniciando servidor Flask...")
    app.run(host="0.0.0.0", port=5000, debug=True)

# created by Jordanlvs 💼, all rights reserved ®
