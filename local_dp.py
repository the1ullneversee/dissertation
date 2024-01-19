from swagger_parser import SwaggerParser
import os
import shutil
import json
model_url = "models/llama-2-7b-chat.Q6_K.gguf"

from llama_cpp import Llama
lcpp_llm = None
llm = Llama(
    model_path=model_url,
    n_threads=2, # CPU cores
    n_batch=512, # Should be between 1 and n_ctx, consider the amount of VRAM in your GPU.
    n_gpu_layers=43, # Change this value based on your model and your GPU VRAM pool.
    n_ctx=4096, # Context window
    verbose=True,
)

class Definition:
    def __init__(self, name, type, properties):
        self.name = name
        self.type = type
        self.properties = properties

    def __str__(self):
        return f"Definition: {self.name}, Properties: {self.properties}"

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.type,
            "properties": self.properties
        }

class Response:
    def __init__(self, status_code, description, schema):
        self.status_code = status_code
        self.description = description
        self.schema = schema

    def __str__(self):
        return f"Response: {self.status_code}, Description: {self.description}, Schema: {self.schema}"

    def to_dict(self):
        return {
            "status_code": self.status_code,
            "description": self.description,
            "schema": self.schema
        }

class Operation:

    def __init__(self, operation, parameters, definitions, responses):
        self.operation = operation
        self.parameters = parameters
        self.definitions = definitions
        self.responses = responses

    def __str__(self):
        return f"Operation: {self.operation}, Parameters: {self.parameters}, Definitions: {self.definitions}, Responses: {self.responses}"

class Resource:

    def __init__(self, path, operations):
        self.path = path
        self.operations = operations

class ParsedApi:

    def __init__(self, file_name, info, resources, path_to_answer):
        self.file_name = file_name
        self.info = info
        self.resources = resources
        self.path_to_answer = path_to_answer

    def __str__(self):
        return f"File: {self.file_name}, Info: {self.info}, Resources: {self.resources}"

    def paths_with_response(self):
        paths = []
        for resource in self.resources:
            for operation in resource.operations:
                if operation.responses:
                    paths.append((resource.path, operation.responses[0]))
        return paths


def parse_api_resources(paths):
    parsed_paths = []

    for path in paths:
        endpoint = parser.paths.get(path)
        parsed_operations = []
        parse_operations(parsed_operations, path, endpoint)
        path = Resource(path, parsed_operations)
        parsed_paths.append(path)
    parsed_api = ParsedApi(file, parser.specification['info'], parsed_paths, {})
    return parsed_api

def parse_operations(parsed_operations, path, endpoint):
    for operation in endpoint:
        parsed_definitions = []
        parsed_parameters = []
        parsed_responses = []
        parameters = endpoint.get(operation).get('parameters')
        parsed_parameters.append(parameters)
        parse_parameters(parsed_definitions, parameters)
        responses = endpoint.get(operation).get('responses')
        parse_responses(parsed_responses, responses, definitions)
        parsed_operations.append(Operation(operation, parameters, parsed_definitions, responses=parsed_responses))

def parse_responses(parsed_responses, responses, definitions):
    try:
        for response_key, response_value in responses.items():
            definition_properties = {}
            if 'schema' in response_value:
                if response_value['schema'].get('$ref'):
                    definition_path = response_value['schema']['$ref']
                    definition = definitions.get(definition_path.split('/')[-1])
                    if definition.get('properties'):
                        definition_properties = definition['properties']
                        for key, value in definition_properties.items():
                            type = value.get('type')
                            direct_ref = value.get('$ref')
                            sub_ref = None
                            if value.get('items'):
                                sub_ref = value.get('items').get('$ref')
                            if sub_ref:
                                definition_path = value['items']['$ref']
                                sub_definition = definitions.get(definition_path.split('/')[-1])
                                definition_properties[key]['items'] = sub_definition
                            elif direct_ref:
                                definition_path = direct_ref
                                sub_definition = definitions.get(definition_path.split('/')[-1])
                                definition_properties[key] = sub_definition
                    else:
                        definition_properties = definition
                else:
                    definition_properties = response_value['schema']
            parsed_responses.append(Response(response_key, response_value['description'], definition_properties))
            definition_properties = None
    except Exception as exc:
        print(exc)
        pass


def parse_parameters(parsed_definitions, parameters):
    param_to_definition = {}
    try:
        for key, value in parameters.items():
            if 'schema' in value:
                if not value['schema'].get('$ref'):
                    parsed_definitions.append(value['schema'])
                    continue
                definition_path = value['schema']['$ref']
                definition = definitions.get(definition_path.split('/')[-1])
                definition_properties = definition['properties']
                for key, value in definition_properties.items():
                    type = value.get('type')
                    direct_ref = value.get('$ref')
                    sub_ref = None
                    if value.get('items'):
                        sub_ref = value.get('items').get('$ref')
                    if sub_ref:
                        definition_path = value['items']['$ref']
                        sub_definition = definitions.get(definition_path.split('/')[-1])
                        definition_properties[key]['items'] = sub_definition
                    elif direct_ref:
                        definition_path = direct_ref
                        sub_definition = definitions.get(definition_path.split('/')[-1])
                        definition_properties[key] = sub_definition
                parsed_definitions.append(definition)
    except Exception as exc:
        print(exc)
        pass



inference_params = {
        "do_sample": True,
        "top_p": 0.6,
        "temperature": 0.9,
        "top_k": 50,
        "max_new_tokens": 512,
        "repetition_penalty": 1.03,
        "stop": ["</s>"],
        "return_full_text": False
    }

def get_instructions(user_content, system_content):

    '''
    Note: We are creating a fresh user content everytime by initializing instructions for every user_content.
    This is to avoid past user_content when you are inferencing multiple times with new ask everytime.
    '''



    instructions = [
        { "role": "system","content": f"{system_content} "},
    ]

    instructions.append({"role": "user", "content": f"{user_content}"})

    return instructions

def build_llama2_prompt(instructions):
    stop_token = "</s>"
    start_token = "<s>"
    startPrompt = f"{start_token}[INST] "
    endPrompt = " [/INST]"
    conversation = []
    for index, instruction in enumerate(instructions):
        if instruction["role"] == "system" and index == 0:
            conversation.append(f"<<SYS>>\n{instruction['content']}\n<</SYS>>\n\n")
        elif instruction["role"] == "user":
            conversation.append(instruction["content"].strip())
        else:
            conversation.append(f"{endPrompt} {instruction['content'].strip()} {stop_token}{startPrompt}")

    return startPrompt + "".join(conversation) + endPrompt

def chat_completion(prompt, system_content):
    instructions = get_instructions(prompt, system_content)
    prompt = build_llama2_prompt(instructions)
    payload = {
      "inputs":  prompt,
      "parameters": inference_params,
      "stream": False ## <-- to have response stream.
    }
    response = llm(
      prompt=prompt,
      max_tokens=256,
      temperature=0.5,
      top_p=0.95,
      repeat_penalty=1.2,
      top_k=50,
      stop = ['USER:'], # Dynamic stopping when such token is detected.
      echo=True # return the prompt
    )

    return response["choices"][0]["text"]

# generate me multiple prompts based on the prompt above:
def get_answer(path, response):
    # create a text prompt
    question = f"Given the following endpoint {path}, write me the HTTP request to get the success response"
    # sub_prompt = f"""[INST] <<SYS>>
    # You are to be given questions about REST API Endpoints. Your answers are to be given in code or text.
    # Give no explanation and provide no Note or opening Sure, and only give the answer in the following format, no fluff text:
    # url: <url> headers: <headers> params: <params> body: <body> python code: <code> code needs to be in Python code using the requests library. Do not include imports, just code.
    # <</SYS>>
    # {question}[/INST]"""
    system_content = '''
    You are a to be given questions about REST API Endpoints. Your answers are to be given in code or text.
    Give no explanation, and only give the answer in the following format, no fluff text:
    url: <url> headers: <headers> params: <params> body: <body> python code: <code> code needs to be in Python code using the requests library. Do not include imports, just code.
    '''
    answer = chat_completion(prompt=question, system_content=system_content)
    return answer, question

def clean_answer(answer):
    try:
        # strip out newlines
        answer = answer.replace("\n", " ")
        # the answer always contains some explanation before the url: tag, so we remove it
    except Exception as exc:
        print(exc)
    return answer

def dump_to_file(questions, answers, main_path):
    folder = main_path
    if not os.path.exists(folder):
        os.mkdir(folder)
    if not os.path.exists(folder+"rest_fine_tune.jsonl"):
        with open(folder+"rest_fine_tune.jsonl", "w") as f:
            f.write("")
    with open(folder+"rest_fine_tune.jsonl", "a") as f:
        for question, answer in zip(questions, answers):
            f.write(json.dumps({"question": question, "answer": answer})+"\n")
    try:
      ssh.connect(hostname=host_name, port = 22, username=user_name, password=password)
      with ssh.open_sftp() as sftp:
        with sftp.open('processed/rest_fine_tune.jsonl', mode='w') as sftp_f:
          for question, answer in zip(questions, answers):
              sftp_f.write(json.dumps({"question": question, "answer": answer})+"\n")
    except Exception as exc:
      print(exc)

def question_answer_generator_from_parsed_api(api: ParsedApi, main_path):
    questions, answers = [], []
    for path_response in api.paths_with_response():
        path, response = path_response[0], path_response[1]
        answer, question = get_answer(path, response)
        answer = clean_answer(answer)
        questions.append(question)
        answers.append(answer)

    paths = [p_r[0] for p_r in api.paths_with_response()]
    question = "Give the following RESTful Endpoint paths. What operations could I perform on them? \n" + json.dumps(paths) + "\n"
    system_content = f'''
        The input will be a list of strings representing resource paths for a RESTFul API. Give you answers as operations a consumer of the API could perform.
        Write the operations in natural language, and separate them with a comma, no fluff text.
    '''
    answer = chat_completion(prompt=question, system_content=system_content)
    answer = clean_answer(answer)

    question = "Give the following RESTful Endpoint paths. What Paths require an entity_id to access and can you get that entity from a different path? If you can which path do you need to call? \n" + json.dumps(paths) + "\n"
    system_content = f'''
        The input will be a list of strings representing resource paths for a RESTFul API.
        Give your response based on which paths require an entity id, and if you can get that entity elsewhere, tell the user how.
        Write the operations in natural language, and separate them with a comma, no fluff text.
    '''
    answer = chat_completion(prompt=question, system_content=system_content)
    answer = clean_answer(answer)
    questions.append(question)
    answers.append(answer)

    dump_to_file(questions, answers, main_path)



import os

# ssh = paramiko.SSHClient()
# logging.getLogger("paramiko").setLevel(logging.WARNING)
# ssh.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
# ssh.load_system_host_keys()
# host_name = "ftpdissertation.blob.core.windows.net"
# user_name = 'ftpdissertation.dissertation.tom'
# password = 'jKCXAV2J34b3uJUZzH6tzP4jBwV0Zd96'


readable = 0
broken_files = []
read = False
definitions = {}
parsed_apis = []


main_path = './swagger-files/'
processing_path = main_path + 'processing/'
processed_path = main_path + 'processed/'
broken_path = main_path + 'broken/'
print(os.path.curdir)
if not os.path.exists(main_path):
  os.mkdir(main_path)
if not os.path.exists(processing_path):
  os.mkdir(processing_path)
if not os.path.exists(processed_path):
  os.mkdir(processed_path)
if not os.path.exists(broken_path):
  os.mkdir(broken_path)

# ssh.connect(hostname=host_name, port = 22, username=user_name, password=password)
# file_list = []
# with ssh.open_sftp() as sftp:
#   files = sftp.listdir()
#   file_list = files

processed_files = os.listdir(processed_path)
files = os.listdir(main_path+'output')

files = files[:int(len(files)/2)]
file_count = len(files)
print(f"There are {file_count} files to process")

for file_name in files:
    try:
        file = file_name
        if file in processed_files or file in broken_path:
          print("processed file or its broken " + file)
          continue
        shutil.move(main_path+"output/"+file, processing_path+file)
        parser = SwaggerParser(swagger_path=processing_path+file)
        print(f"{parser.specification['info']['description']} has {len(parser.paths)} paths")
        paths = list(parser.paths.keys())
        for key, value in parser.specification['definitions'].items():
            definitions[key] = value
        parsed_api = parse_api_resources(paths)
        parsed_apis.append(parsed_api)
        question_answer_generator_from_parsed_api(parsed_api, main_path)
        # move file to processed folder.
        shutil.move(processing_path+file, processed_path+file)
        readable += 1
        read = True
        print(f"--- processed {readable} out of {file_count} ---")

    except Exception as exc:
        print(exc)
        broken_files.append(file)
        shutil.move(processing_path+file, broken_path+file)
print(readable)
print(len(broken_files))