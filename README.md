# 🔐 SunShield - Central de Monitoramento - PLIVO

Este é um sistema automatizado para **verificação de segurança por chamada de voz**, ideal para monitoramento de ambientes remotos. Utiliza **Twilio** para realizar ligações em horários pré-definidos e ouvir uma resposta verbal.

---

## ⚙️ Funcionalidades

- ✅ Ligações automáticas em horários específicos
- ✅ Verificação por voz com resposta esperada ("protegido")
- ✅ Segunda tentativa caso a resposta não seja entendida
- ✅ Alerta automático a contato de emergência em caso de falha
- ✅ Painel web para gerenciar os contatos
- ✅ Compatível com deploy no Render.com

---

## 🖥️ Painel de Contatos

Acesse:

https://confirmation-u5hq.onrender.com/painel-contatos.html


No painel é possível:
- Adicionar contatos
- Excluir contatos
- Ver a lista de contatos

> O contato de emergência deve ter o nome salvo como:  
> `emergencia`

---

## 📞 Testar verificação manualmente

Você pode forçar uma ligação de teste para qualquer contato salvo acessando:

https://confirmation-u5hq.onrender.com/<nome_do_contato>


**Exemplo:**

https://confirmation-u5hq.onrender.com/verificacao1


---

## 🗂️ Estrutura esperada

├── app.py
├── contacts.json
├── painel-contatos.html
├── requirements.txt
├── .gitignore
└── README.md

---

## 📋 Exemplo de `contacts.json`

```json
{
  "verificacao1": "+5511999999999",
}

```

## 👨‍💻 Desenvolvido por

**Jordanlvs 💼**  
*Desenvolvedor do sistema Callfirmation - SunShield*  
