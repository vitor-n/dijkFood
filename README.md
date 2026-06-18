# dijkFood

*Desenvolvido por Anderson Falcão, João Felipe Villas Boas, Pedro
Tokar e Vitor do Nascimento.*

-------------------------------------------------------------------------------

## Sobre o repositório

Esse repositório é destinado à primeira avaliação da matéria de Computação
em Nuvem, eletiva ofertada em 2026.1 da graduação de Ciência de Dados e
Inteligência Artificial da FGV-EMAp.

O trabalho consiste em desenhar uma arquitetura usando serviços da AWS (ECS,
RDS, EC2, S3 e DynamoDB) para simular um serviço de gerenciamento de entregas
de comida. O serviço conta com gerenciamento de usuários, restaurantes, pedidos
(incluindo seus estados) e a posição dos entregadores. Ele é disponibilizado
por meio de uma API REST, que oferece endpoints para os usuários do sistema
poderem realizar as tarefas de criação de pedidos, tracking de entregadores, etc.

O sistema usa serviços de autoscaling da AWS e de roteamento de requests 
(o ALB do ECS) para gerenciar os recursos alocados de forma inteligente,
alocando mais unidades de computação quando o serviço passa a receber um número
muito grande de requests por segundo (simulando situações da vida real como
feriados ou dias chuvosos). Mais detalhes a respeito da arquitetura e da
implementação estão presentes no relatório.

## Entregáveis

Relatório A1: abrir arquivo [`Computação em Nuvem - A1.pdf`](./Computação%20em%20Nuvem%20-%20A1.pdf)

Relatório A2: abrir arquivo [`Computação em Nuvem - A2.pdf`](./Computação%20em%20Nuvem%20-%20A2.pdf)

Vídeo de implantação e demonstração do sistema: [Google Drive](https://drive.google.com/drive/folders/1VnNJ-_aKwBaFoFUj4qqwe-s08gBdGnKt?usp=sharing)

## Instruções de execução

> **⚠️ ATENÇÃO:** O script e a infraestrutura foram pensados para serem executados
em um Learner Lab, e dependem da Role de `LabRole` do IAM. O deploy
potencialmente não funcionará fora do ambiente Learner Lab.

### Pré-requisitos

Para que a alocação automática de recusos funcione corretamente, é necessário
que você tenha instaladas em seu computador as ferramentas 
[AWS CLI](https://aws.amazon.com/pt/cli/) e 
[Docker CLI](https://www.docker.com/products/cli/). Para testar o funcionamento
delas, execute em seu terminal:

```bash
$ docker -v
$ aws --version
$ docker run hello-world
```

É esperado que os dois primeiros comandos mostrem as versões das ferramentas,
e o último deve mostrar uma mensagem do docker afirmando que a sua instalação
está funcionando corretamente.

Com as ferramentas instaladas, é necessário que você informe previamente suas
credenciais de acesso da AWS. Para isso, acesse a tela de início do laboratório
da AWS Academy, aperte no botão "AWS Details" e no botão "Show" em frente ao
título "AWS CLI". Copie as credenciais mostradas para o arquivo
`~/.aws/credentials".

Por último, é necessário criar um ambiente Python com as bibliotecas necessárias
para a execução do script de deploy. Para isso, crie um ambiente com a
ferramenta de sua preferência, e com ele ativo, execute:

```bash
$ pip install -r requirements.txt
```

### Execução

O script lê duas variáveis de ambiente: `DB_USERNAME` e `DB_PASSWORD`. Elas são
usadas para configurar as credenciais de acesso ao banco de dados (vale
ressaltar que ele não ficará aberto publicamente). Defina essas variáveis em um
arquivo `.env` ou por meio do comando `export` em seu terminal. Caso elas não
sejam fornecidas, um valor padrão será utilizado.

Após definir as credenciais, execute:

```bash
$ python deploy.py all
```

O script irá começar a subir a infraestrutura em sua AWS, levando em torno de
25 minutos. Quando esse processo terminar, o script irá imprimir na tela o link
do ALB para acesso da API. É possível acessar o endpoint `docs/` com o navegador
para explorar os endpoints e entidades do serviço `core-api`.

Após isso, o script irá enviar a simulação para ser feita em uma instância EC2
dedicada, por meio do SSM Agents. Os logs da execução poderão ser acompanhados
no console da AWS via CloudWatch (o link para acesso direto no console d AWS
será impresso no terminal), de forma que a saída do script não fique poluída
com eles.


Após o término da simulação, os recursos da AWS serão automaticamente destruídos, deixando o ambiente assim como foi encontrado anteriormente. Esse processo poderá **falhar** caso alguma alteração seja feita no console da AWS durante a execução do script, então é importante que os recursos não sejam manipulados via console enquanto o script estiver em execução.

## Camada Analítica e Integração com Amazon Bedrock

O sistema conta com uma **Camada Analítica (Objetivo 3)** composta por:
* **Dashboard Service:** API e interface operacional que exibe métricas agregadas da operação de delivery em tempo real.
* **Assistant Service (Chatbot):** Interface conversacional que permite realizar perguntas em linguagem natural sobre a operação (ex: *"quantos pedidos foram entregues hoje?"*).
* **Prediction Service (ETA):** Modelo preditivo de estimativa de tempo de entrega baseado em machine learning.

A camada analítica consome dados estruturados em formato Parquet no S3 Data Lake através do **AWS Glue** e **Amazon Athena**.

### Funcionamento do Chatbot e Fallback
O `assistant-service` utiliza o **Amazon Bedrock** (modelo `amazon.nova-micro-v1:0` por padrão) para traduzir perguntas em linguagem natural para queries SQL (Text-to-SQL) e para sumarizar os resultados obtidos.

* **Restrição do Learner Lab (AWS Academy):** O perfil padrão `LabRole` fornecido pela AWS Academy **não possui permissão** para invocar modelos no Amazon Bedrock.
* **Fallback Determinístico:** Para contornar essa restrição sem quebrar a aplicação, o chatbot possui um motor determinístico (`fallback.py`). Se a chamada ao Bedrock falhar por permissão, o chatbot reconhece padrões comuns de perguntas via expressão regular, gera a query SQL correspondente e retorna os dados reais consultados no Athena/S3 de forma transparente.

### Configurando o Bedrock via Conta Real (Modo Híbrido)
Se você possui uma conta AWS real com acesso ao Bedrock e quer utilizá-la em conjunto com a infraestrutura rodando no Learner Lab da AWS Academy:

1. **Crie um IAM User na sua conta real** com permissões para invocar modelos no Bedrock (ex: anexe a política `AmazonBedrockFullAccess`).
2. **Gere chaves de acesso (Access Key e Secret Key)** para esse usuário.
3. Na raiz do projeto (mesmo local do `deploy.py`), crie um arquivo chamado `.env` e configure as credenciais da conta real (elas serão carregadas automaticamente pelo deploy):
   ```env
   BEDROCK_AWS_ACCESS_KEY_ID="SUA_ACCESS_KEY_DA_CONTA_REAL"
   BEDROCK_AWS_SECRET_ACCESS_KEY="SUA_SECRET_KEY_DA_CONTA_REAL"
   BEDROCK_REGION="us-east-1"                 # Região onde o modelo está ativo
   BEDROCK_MODEL_ID="amazon.nova-micro-v1:0"  # ID do modelo liberado
   ```
4. Execute o deploy (`python deploy.py update` ou `deploy`).

> **⚠️ AVISO DE CUSTOS:** Como os modelos de linguagem são tarifados por token na conta real, **monitore rigorosamente o consumo** no painel de Billing da AWS para não estourar o orçamento do seu grupo (ex: limite de $10 USD). É recomendável configurar o AWS Budgets para receber alertas automáticos de gasto.

*Nota: Esse design mantém as consultas do Athena locais na AWS Academy utilizando a role nativa do contêiner, e redireciona de forma isolada apenas as chamadas do LLM (Bedrock) para a conta real usando as chaves informadas.*

