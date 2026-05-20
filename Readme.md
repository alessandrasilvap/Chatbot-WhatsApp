<img width="1365" height="598" alt="Captura de tela 2026-05-20 005721" src="https://github.com/user-attachments/assets/9651d775-d1c9-4faf-9627-79afd7f5e5e0" />

# 🤖 Chatbot WhatsApp

Este projeto é um chatbot integrado à API da Meta para atendimento automatizado via WhatsApp.

Atualmente, o projeto já evoluiu incluindo um painel web simples, onde um atendente humano pode responder os usuários manualmente, já que a API não permite que o número conectado seja utilizado diretamente no WhatsApp.

---

## 🎯 Objetivo

Criar uma solução híbrida de atendimento:

* 🤖 Chatbot automático para respostas rápidas
* 👩‍💻 Interface web para atendimento humano

---

## 🧠 Como funciona

1. O usuário envia mensagem pelo WhatsApp
2. A API da Meta recebe e envia para o backend
3. O chatbot processa a mensagem (Python + Flask)
4. As mensagens poderão ser visualizadas em um painel web para resposta manual

---

## 🛠 Tecnologias utilizadas

* Python (Flask)
* API da Meta (WhatsApp Cloud API)
* Front-end (HTML, CSS e JavaScript)
* MySQL
* Power BI (para análise de dados)
* Google Cloud

---

## ⚙️ Como rodar o projeto

### Pré-requisitos:

* Python instalado
* MySQL configurado
* Conta e credenciais da API da Meta

### Passos:

```bash
# Clone o repositório
git clone [https://github.com/seu-usuario/seu-repositorio.git](https://github.com/alessandrasilvap/Chatbot-WhatsApp.git)

# Entre na pasta
cd seu-repositorio

# Crie o ambiente virtual
python -m venv venv

# Ative o ambiente
venv\Scripts\activate  # Windows

# Instale as dependências
pip install -r requirements.txt

# Configure o arquivo .env com suas credenciais

# Execute o projeto
python codigo3.py
```

---

## 🔐 Segurança

* O arquivo `.env` não está incluído no repositório por conter informações sensíveis

---

## 🚧 Status do projeto

🚧 Em teste

* [x] Integração com API da Meta
* [x] Estrutura inicial do chatbot
* [x] Interface web para atendimento humano
* [x] Integração com banco de dados completa
* [x] Deploy no Google Cloud

---

## 🤝 Contribuição

Contribuições são bem-vindas!

Sinta-se à vontade para:

* Abrir issues
* Sugerir melhorias
* Criar pull requests

---

## 📌 Observações

Este projeto está sendo desenvolvido para fins de aprendizado e evolução profissional.
