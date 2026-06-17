# Documentação do projeto para migração corporativa

## Inventário da Arquitetura
### Módulos:
- Chatbot
- Painel Atendimento Humano
- Painel Disparos

### Arquitetura Atual:
- Frontend

├── Painel Atendimento

├── Painel Disparos

├── Login

- Backend

├── Webhook Meta

├── Chatbot

├── Atendimento Humano

├── Disparos

├── Auditoria

- Infraestrutura

├── Nginx

├── Gunicorn

├── Redis

├── MySQL

├── Systemd

- Integrações

├── Meta WhatsApp API

├── Power BI

---

## Sistemas Integrados

### Meta WhatsApp Cloud API

Responsável por:
- Recebimento de mensagens
- Envio de mensagens
- Templates
- Status de entrega
- Status de leitura

### Power BI

Responsável por:
- Dashboards operacionais
- Indicadores gerenciais
- Métricas de atendimento
- Acompanhamento de desempenho

---

## Banco de Dados

Banco de dados: **bot_atendimento**

Tabelas: *atendentes, atendimento_eventos, atendimentos, disparos, disparos_contatos, sessao_usuario*.

- **atendentes**: id, usuario, senha, permissao, tentativas_login, bloqueado_ate;
  - Finalidade: Armazenar os usuários internos do sistema responsáveis pelo atendimento humano e administração do painel. Também controla permissões de acesso, autenticação e bloqueios temporários por tentativas incorretas de login.
  - Registros Hoje: 3
- **atendimento_eventos**: id, atendimento_id, tipo_evento, valor, data_evento, external_message_id;
  - Finalidade: Registrar todo o histórico operacional dos atendimentos. Funciona como trilha de auditoria do sistema, armazenando mensagens, transferências para atendente, encerramentos, identificação do usuário e demais eventos ocorridos durante o atendimento.
  - Observação: É a tabela com maior potencial de crescimento, pois registra todas as interações realizadas no sistema.
  - Registros Hoje: 2175
- **atendimentos**: id, telefone, telefone_bot, nome, matricula, menu_id, sub_id, sub_sub_id, resposta_bot, status, atendente_nome, assumido_em, tipo_periodo;
  - Finalidade: Representa o atendimento principal do usuário. Armazena o estado atual da conversa, responsável pelo atendimento, informações do usuário e status operacional do atendimento.
  - Registros Hoje: 251
- **disparos**: id, numero_id, template_nome, total_contatos, enviados, erros, data_criacao, status;
  - Finalidade: Armazenar as campanhas de envio em massa realizadas pelo sistema, contendo informações gerais da campanha e seus resultados.
  - Registros Hoje: 45
- **disparos_contatos**: id, disparo_id, nome, telefone, variaveis_json, status, erro_msg, tentativas, wamid, data_envio, data_status_update;
  - Finalidade: Armazenar o detalhamento individual de cada destinatário de uma campanha de disparo, incluindo status de envio, erros, tentativas realizadas e identificadores retornados pela Meta.
  - Registros Hoje: 639
- **sessao_usuario**: telefone, telefone_id, atendimento_id, etapa, nome, matricula, menu_id, sub_id, sub_sub_id, atendente_chamado, resumo_handoff_salvo, ultimo_contato, atualizado_em;
  - Finalidade: Controlar o estado atual do chatbot para cada usuário. Permite que o fluxo da conversa seja retomado corretamente entre mensagens, mantendo o contexto do atendimento.
  - Registros Hoje: 1
  
---

## Serviços da VM
### Serviços do Projeto

- bot-webhook.service

  - Recebe os webhooks da Meta.
  - Realiza validações iniciais.
  - Enfileira mensagens no Redis.

- bot-fila.service

  - Worker RQ responsável por processar mensagens da fila Redis.

- bot-worker.service

  - Worker responsável por tarefas automáticas, timeouts e manutenção de atendimentos.

### Serviços de Infraestrutura

- mysql.service

  - Banco de dados principal da aplicação.

- redis-server.service

  - Fila assíncrona, deduplicação e comunicação interna.

- nginx.service

  - Proxy reverso e servidor web.

### Serviços de Monitoramento / Cloud

- google-cloud-ops-agent.service
- google-cloud-ops-agent-fluent-bit.service
- google-cloud-ops-agent-opentelemetry-collector.service

Responsáveis pela integração com monitoramento do Google Cloud.

### Observação

Atualmente a aplicação opera através de múltiplos serviços independentes, permitindo separação entre recepção de mensagens, processamento assíncrono e manutenção do sistema.

---

## Variáveis de Ambiente

- DB_HOST;
- DB_PORT;
- DB_USER;
- DB_PASSWORD;
- DB_NAME;
- DATA_CORTE_PRODUCAO;
- WA_VERIFY_TOKEN;
- WA_ACCESS_TOKEN;
- WA_PHONE_NUMBER_ID;
- WA_PHONE_NUMBER_ID_DISPAROS;
- WA_API_VERSION;
- WA_APP_SECRET;
- APP_SECRET_KEY;

---

## Fluxos
### Fluxo de Atendimento
Mensagem

↓

Meta API

↓

Webhook

↓

Redis

↓

Worker

↓

Banco de Dados

↓

Resposta

↓

Meta API

↓

Usuário

### Fluxo de Handoff
Usuário

↓

Solicita Atendente

↓

Fila de Atendimento

↓

Atendente Assume

↓

Painel Web

↓

Atendimento Humano

### Fluxo de Disparo
Painel Disparos

↓

Importação CSV/Excel

↓

Validação dos Dados

↓

Criação da Campanha

↓

Fila Redis

↓

Worker de Envio

↓

Meta API

↓

Atualização de Status

↓

Banco de Dados

↓

Painel

---

## Pontos de Atenção para Migração

### Migrar
- Python → PHP
- MySQL → SQL Server
  
### Avaliar
- Redis
- Workers
- WebSocket

### Melhorar
- Retry
- Teste de carga
- Monitoramento

---

## Pontos Fortes e Evolução
Pontos Fortes

- Arquitetura assíncrona
- Redis
- Workers
- Pool de conexões
- Auditoria
- HMAC Meta
- WebSocket
- Hash de senhas
- Controle de força bruta
- Deduplicação de mensagens via Redis e Banco de Dados
- Pool de conexões para banco configurado para até 32 conexões simultâneas

Características Arquiteturais

- Processamento assíncrono através de Redis e Workers.
- Pool de conexões para banco de dados.
- Deduplicação de mensagens.
- Comunicação em tempo real via WebSocket.
- Auditoria completa de eventos.
- Integração oficial com Meta WhatsApp Cloud API.
- Health Check para monitoramento.

Pontos para Evolução

- Testes formais de carga
- Estratégia de retry
- Recuperação após indisponibilidade do Redis
- Monitoramento corporativo
- Migração SQL Server
- Migração PHP
