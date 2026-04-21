# dijkFood

## Instruções de execução

### Pré-requisitos

Para que a alocação automática de recusos funcione corretamente, é necessário
que você tenha instaladas em seu computador as ferramentas 
[AWS CLI](https://aws.amazon.com/pt/cli/) e 
[Docker CLI](https://www.docker.com/products/cli/). Para testar o funcionamento
delas, execute em seu terminal:

```bash
$ docker -v
$ aws --version
$ docker run hello-worl
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
$ python deploy.py deploy
```

O script irá começar a subir a infraestrutura em sua AWS, levando em torno de
25 minutos.

> **⚠️ ATENÇÃO:** O script e a infraestrutura foram pensados para serem executados
em um Learner Lab, e dependem da Role de `LabRole` do IAM. O deploy
potencialmente não funcionará fora do ambiente Learner Lab.
