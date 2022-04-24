import random, uuid
from utility import (
  setInterval, split_large_text, available_languages,
  create_blocks_to_analyze, read_redis_db
)
from typing import Optional
from io import BytesIO

from fastapi import (
  FastAPI, File, UploadFile, Form,
  BackgroundTasks, HTTPException, Response
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
# https://stackoverflow.com/questions/71966225/request-from-client-side-stays-pending-fast-api
#PDF MINER

from pdfminer.converter import PDFPageAggregator
from pdfminer import pdfparser, pdfinterp, pdfpage
from pdfminer.pdfdocument import PDFDocument
from pdfminer.layout import LTTextBoxHorizontal, LAParams
#SPACY
import spacy
from spacy.language import Language
from spacy_langdetect import LanguageDetector

import redis

r = redis.Redis(host='localhost', port=6379)
r.set("France", "Paris")
r.hmset("Germany", {"capital": "Berlin", "population": 80000000, "lang": "deutsch"})
r.hset("Germany", "lang", "german")
print(r.hgetall("Germany"))

store_tasks = {}

def process_text(
  text, id, remove_stop_words = True, pdf = False
  ):
  try:
    # https://stackoverflow.com/questions/66712753/how-to-use-languagedetector-from-spacy-langdetect-package
    @Language.factory("language_detector")
    def get_lang_detector(nlp, name):
      return LanguageDetector()

    # We test them just to know the language
    if len(text) < 1: raise Exception("We couldn't find any text on your file")
   
    block_to_test = random.choices(text, k = 10)
    block_to_test = '\n'.join(block_to_test)
    # create the first language in english
    nlp_en = spacy.load("en_core_web_sm")
    # add language detector to the pipeline
    nlp_en.add_pipe('language_detector', last=True)
    # create the first doc just in order to check the language
    doc = nlp_en(block_to_test) # Time consuming but we won't take it into consideration
    # Guess the language of the text
    lang_doc = doc._.language['language']
    # Check the degree of accuracy of the previous check
    score_lang_doc = doc._.language['score']

    store_tasks[id]["language"] = {
      "language": lang_doc,
      "score": score_lang_doc
    }
    # r.hset(id, "language", )

    # If the language isn't available use english
    language_available = lang_doc in available_languages["initials"]
    language = available_languages["object"][lang_doc] if language_available  else "en_core_web_sm"
    # create the final language according to our guess
    nlp = spacy.load(language)

    #create blocks of text
    blocks_to_parse = create_blocks_to_analyze(text)
    text = None # save memory

    # Environ 50% du temps à lire étudier le doc avec spacy pour un doc de 1500 pages
    percentage_taken = 50 if pdf else 90
    percentage_each_page = percentage_taken/len(blocks_to_parse)

    word_counter = {}

    # Environ 50% du temps global pour un doc de 1500 pages 
    for block in blocks_to_parse:
      doc = nlp(block)
      for token in doc:

        lemma = token.lemma_.lower()

        if token.is_punct: continue 
        if token.is_digit: continue 
        if token.is_space: continue
        if token.is_stop and remove_stop_words: continue

        if lemma in word_counter: 
          word_counter[lemma] = word_counter[lemma] + 1
        else:
          word_counter[lemma] = 1

      store_tasks[id]["progression"] += percentage_each_page

    store_tasks[id]["counter"] = word_counter
    store_tasks[id]["progression"] = 100
    return True
  except Exception as e:
    store_tasks[id] = {"error": True, "message": e}
    return False

def convert_pdf_to_text(file, id):
  try:
    #Convert file into an in memory binary file
    file = BytesIO(file)

    # GET THE NUMBER OF PAGES
    parser = pdfparser.PDFParser(file)
    parsed_document = PDFDocument(parser)
    pages_document = parsed_document.catalog['Pages']
    number_of_pages = pdfinterp.resolve1(pages_document)['Count']
    
    # Environ 40% du temps à lire les pages pour un doc de 1500 pages
    #Pas nécessaure on utilise uniquement cette fonction si c'est un pdf
    percentage_taken = 40
    percentage_each_page = percentage_taken/number_of_pages

    rsrcmgr = pdfinterp.PDFResourceManager()
    laparams = LAParams()
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = pdfinterp.PDFPageInterpreter(rsrcmgr, device)

    listLines = []

    # Environ 40% du temps pour un doc de 1500 pages
    for page in pdfpage.PDFPage.get_pages(file):
      interpreter.process_page(page)
      # receive the LTPage object for the page.
      layout = device.get_result()
      for element in layout:
        if isinstance(element, LTTextBoxHorizontal):
          page_text  = element.get_text().strip()
          listLines.append(page_text)
      store_tasks[id]["progression"] += percentage_each_page
    return listLines
  
  except Exception as e:
    store_tasks[id] = {"error": True, "message": e.message, "progression": 0} 
    return False

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.get("/polling/{task_id}", status_code=200)
def polling(task_id: str, response: Response):
  response.headers['Connection'] = 'close'
  try:
    rep = {}
    rep = {"success": True, "id": task_id, 
    "state": "ongoing", "progression": store_tasks[task_id]["progression"]}

    print("error" in store_tasks[task_id])
    print(store_tasks)
  
    progression = store_tasks[task_id]["progression"]
    rep["progression"] = progression
    if progression >= 100:
      rep["finish"] = True
    else:
      rep["finish"] = False
    rep["success"] = True
  except:
    raise HTTPException(
      status_code=400, detail="Une erreur est survenue en récupérant les données"
      )

  return rep

@app.get("/unsuccessful-polling/{task_id}")
def unsuccessful_polling(task_id: str):

  store_tasks[task_id] = None 

  return {"success": True}

@app.get('/test/redis')
def test_redis():
  german_capital = r.get('Germany').decode('ascii')
  return  { "germany": german_capital}

@app.get("/successful-polling/{task_id}")
def polling(task_id: str):

  rep = {"success": True}
  rep["stats"] = store_tasks[task_id]

  store_tasks[task_id] = None

  return rep

async def launch_process(id, file, stopW, txt):
  store_tasks[id] = {"progression": 5}
  all_good = True 
  try:
    if file:
      type_of_file = file.content_type
      content = await file.read()
             
      if type_of_file == 'application/pdf':
        
        # text_pdf = convert_pdf_to_text(content, id)
        # all_good = process_text(text_pdf, id, stopW, True)
        text_pdf = await run_in_threadpool(lambda: convert_pdf_to_text(content, id))
        print("TYPE !!", type(text_pdf))
        all_good = await run_in_threadpool(lambda: process_text(text_pdf, id, stopW, True))

      elif type_of_file == 'text/plain':
        # Decode bytes ==> string
        content = content.decode("utf-8")
        max_size_blocks = 15000
        # If the text is too large
        content = await run_in_threadpool(lambda: split_large_text(content, max_size_blocks))
        all_good = await run_in_threadpool(lambda: process_text(content, id, stopW, False))

      else:
        Exception("Le fichier n'est ni de type texte ni de type pdf")

    # if we don't have to read a file
    else:
      if txt:
        all_good = await run_in_threadpool(lambda: process_text(txt, id, stopW, False))
      else:
        raise Exception("Le texte est vide...")

    if not all_good: raise Exception("Problème lors de l'analyse du texte")

  except Exception as e:
    store_tasks[id] = {"error": True, "message": e.message}
  finally:
    return

# @app.post("/", status_code=202)
@app.post("/", status_code=202)
# async def read_root(
def read_root(
  background_tasks: BackgroundTasks,
  file: Optional[UploadFile] = File(None), 
  stopWords: Optional[bool] = Form(True),
  text: Optional[str] = Form(None),
):
  task_id = str(uuid.uuid4())
  try:
    background_tasks.add_task(launch_process, task_id, file, stopWords, text)
    return { 
      "state": 'ongoing', "id": task_id, "success": True 
      }
  except:
    detail_http={
      "state": "unsuccessful", "id": task_id, "success": False
      }
    raise HTTPException(status_code=400, detail=detail_http)

# Know the state of the store
# To remove in production

def print_store():
  read_redis_db(r)

setInterval(30, print_store)