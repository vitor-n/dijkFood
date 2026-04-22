# dijkFood



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

Após o término da simulação, os recursos da AWS serão automaticamente destruídos,
deixando o ambiente assim como foi encontrado anteriormente. Esse processo
poderá **falhar** caso alguma alteração seja feita no console da AWS durante a
execução do script, então é importante que os recursos não sejam manipulados
via console enquanto o script estiver em execução.
