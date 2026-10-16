# Agenda do Google (3 contas)

O Jarvis lê e escreve no Google Calendar por uma **conta de serviço** (um "robô" do Google com e-mail próprio, chave que não expira). Cada agenda que ele deve enxergar é **compartilhada com esse e-mail**.

| chave | conta | o que vai nela |
|---|---|---|
| `trabalho` | felipefenske05@gmail.com | tarefas e eventos profissionais |
| `pessoal` | felipefenske12@gmail.com | pessoal, viagens, lazer |
| `cafe` | admin@cafelabs.net | reuniões e coisas da empresa |

Leitura junta as três (o mesmo evento em duas contas aparece uma vez, com as duas). Ao criar, a conta vem das palavras ("reunião com o cliente" → Café, "dentista" → pessoal, "na pessoal" → pessoal); sem pista, o Jarvis pergunta. Mover e apagar sempre pedem "sim"; criar mostra o botão **Desfazer**; se já há algo no horário, ele pergunta antes.

## Ligar (uma vez)

1. https://console.cloud.google.com → escolher/criar um projeto → **APIs e serviços → Biblioteca → Google Calendar API → Ativar** (não precisa de faturamento).
2. **IAM e administrador → Contas de serviço → Criar** (nome `jarvis-agenda`, sem papéis) → abrir a conta → **Chaves → Adicionar chave → JSON**. Baixa um arquivo; **é segredo**.
3. Guardar o arquivo no notebook como `state/google-service-account.json` (a pasta `state/` fica fora do git) ou apontar outro caminho em `JARVIS_GOOGLE_CREDENTIALS`.
4. Em **cada uma das 3 contas**: Google Calendar (no computador, ou "versão para computador" no celular) → ⚙ da agenda → **Compartilhar com pessoas específicas** → adicionar o e-mail da conta de serviço (`...@...iam.gserviceaccount.com`, está no JSON em `client_email`) com a permissão **Fazer alterações em eventos**.
   - `admin@cafelabs.net` é Google Workspace: o administrador (o próprio Felipe) precisa liberar, em *Admin → Apps → Google Workspace → Agenda → Compartilhamento externo*, "compartilhar todas as informações, e pessoas de fora podem alterar eventos".
5. No `.env`:
   ```
   JARVIS_CALENDARS=trabalho=felipefenske05@gmail.com,pessoal=felipefenske12@gmail.com,cafe=admin@cafelabs.net
   ```
6. Reiniciar o bot (botão Reiniciar na bandeja). Sem o JSON, as ferramentas de agenda ficam desligadas e o log avisa.

## Limites conhecidos

- A conta de serviço **não convida participantes nem cria link do Meet** (isso exigiria delegação em todo o domínio, só Workspace). Por isso o Jarvis marca o evento, mas não convida ninguém.
- Evento que se repete ("toda segunda") ainda não: o Jarvis diz isso e sugere um lembrete.
- Mover/cancelar procura o título nos próximos 60 dias; com mais de um resultado, pede mais palavras.
- Se uma conta falha na leitura, ela aparece como "Não consegui ler: ..." em vez de sumir.

## Tarefas do dia no Calendar (agenda separada)

O plano diário do Jarvis (`/plano`) pode aparecer no Calendar como itens de **dia inteiro**, numa agenda só pra isso (ex.: "Jarvis · tarefas", criada na conta 05). É **sentido único**: o Jarvis escreve, o Calendar só mostra; o que for editado lá é desfeito na próxima sincronização.

- Um item por tarefa, no dia que o plano dá. Concluída vira "✓ título". Sobrou, anda pro dia seguinte. Saiu do plano (concluída no Mind, pulada), some. Os dias que já passaram ficam como histórico.
- Sincroniza ao atualizar o plano (meia-noite, ou ao subir o bot), ao concluir ("concluí X") e ao adiantar uma tarefa.
- Nunca mexe nas agendas de eventos: só em itens com id `jvt…` da agenda de tarefas.

Ligar: criar a agenda → compartilhar com a conta de serviço ("Fazer alterações em eventos") → copiar o **ID da agenda** (⚙ da agenda → *Integrar agenda*) → `.env`: `JARVIS_TASKS_CALENDAR=<id>` → reiniciar o bot.

Decisão de 2026-10-16: **Google Tasks descartado** (a conta de serviço não alcança Tasks e o login OAuth exigia reautorizar a cada 7 dias, porque o Google não deixou publicar o app). Quando o app próprio do Jarvis existir, tarefas e eventos moram nele e o Calendar fica só pra reuniões da Café.
