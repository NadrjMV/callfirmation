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
base_url = os.getenv("BASE_URL")

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

# Atualização da função ligar_para_verificacao_por_nome
def ligar_para_verificacao_por_nome(nome):
    print(f"[LIGAR_PARA_VERIFICACAO_POR_NOME] Ligando para o contato '{nome}'.")
    
    contatos = load_contacts()
    numero = contatos.get(nome.lower())

    if not numero:
        raise ValueError(f"Contato '{nome}' não encontrado.")

    if not validar_numero(numero):
        raise ValueError(f"Número '{numero}' do contato '{nome}' é inválido.")

    sid = ligar_para_verificacao(numero)
    
    if not sid:
        raise RuntimeError(f"A chamada para o número '{numero}' falhou (SID vazio).")
    
    return sid

# Modificação na função forcar_ligacao
@app.route("/forcar_ligacao/<nome>", methods=["GET"])
def forcar_ligacao(nome):
    try:
        print(f"Tentando iniciar ligação para: {nome}")
        sid = ligar_para_verificacao_por_nome(nome)  # usa a função corrigida
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

# O restante do código continua inalterado
@app.route("/testar-verificacao/<nome>")
def testar_verificacao(nome):
    print(f"[TESTAR_VERIFICACAO] Requisição para testar verificação do contato: {nome}")
    sid = ligar_para_verificacao_por_nome(nome)
    if sid:
        print(f"[TESTAR_VERIFICACAO] Ligação iniciada para {nome} com SID: {sid}")
        return f"Ligação de verificação para {nome} iniciada. SID: {sid}"
    print(f"[TESTAR_VERIFICACAO] Erro ao iniciar ligação para {nome}.")
    return f"Erro ao iniciar ligação para {nome}.", 400

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

    # Criando a chamada
    app.logger.info(f"Criando chamada para {numero_destino} com número de origem {signalwire_number}")
    chamada = client.calls.create(
        to=numero_destino,
        from_=signalwire_number,
        url=f"{base_url}/twiml-script"
    )

    # Diagnóstico: Verifique se o SID foi retornado
    print(f"[LIGAR_PARA_EMERGENCIA] Detalhes da resposta da chamada: {chamada}")

    if not chamada or not chamada.sid:
        print(f"[LIGAR_PARA_EMERGENCIA] Chamada retornou SID inválido: {chamada}")
        raise RuntimeError("Erro ao iniciar chamada de emergência.")

    print(f"[LIGAR_PARA_EMERGENCIA] Chamada de emergência iniciada. SID: {chamada.sid}")
    return chamada.sid

@app.route("/verifica-emergencia", methods=["POST"])
def verifica_emergencia():
    resposta = request.form.get("SpeechResult", "").lower()
    tentativa = int(request.args.get("tentativa", 1))
    print(f"[VERIFICA_EMERGENCIA] Resposta recebida - Tentativa {tentativa}: '{resposta}'")

    if "ok" in resposta:
        print("[VERIFICA_EMERGENCIA] Palavra-chave 'OK' detectada. Emergência confirmada.")
        return _twiml_response("Confirmação recebida. Obrigado.", voice="alice")

    if tentativa < 2:
        resp = VoiceResponse()
        record_action_url = f"{base_url}/verifica-emergencia?tentativa={tentativa + 1}"
        resp.say("Não entendi. Por favor diga OK para confirmar.", language="pt-BR", voice="alice")
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

    print("[VERIFICA_EMERGENCIA] Falha na confirmação da emergência.")
    return _twiml_response("Falha na confirmação. Encerrando ligação.", voice="alice")

@app.route("/twiml-script")
def twiml_script():
    resp = VoiceResponse()
    resp.say("Central de monitoramento?", voice="alice", language="pt-BR")
    resp.record(
        action=f"{base_url}/verifica-sinal?tentativa=1",
        method="POST",
        max_length=5,
        play_beep=True,
        timeout=5,
        transcribe=True,
        transcribe_callback=f"{base_url}/verifica-sinal?tentativa=1",
        trim="trim-silence",
        recording_status_callback=f"{base_url}/verifica-sinal?tentativa=1",
        recording_status_callback_method="POST",
        language="pt-BR"
    )
    return Response(str(resp), mimetype="text/xml")

if __name__ == "__main__":
    print("[APP] Iniciando servidor Flask...")
    app.run(host="0.0.0.0", port=5000, debug=True)

# created by Jordanlvs 💼, all rights reserved ®
