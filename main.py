import random, uuid, json, os
from collections import Counter
from typing import Optional
from io import BytesIO
from datetime import datetime

from utility import (
  setInterval, split_large_text,  create_blocks_to_analyze,
  available_languages, word_pos, sort_word_arr,
  remove_old_tasks
)

#FAST API
from fastapi import (
  FastAPI, File, UploadFile, Form,
  BackgroundTasks, HTTPException, Response
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pdfminer import pdfparser, pdfinterp, pdfpage
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdocument import PDFDocument
from pdfminer.layout import LTTextBoxHorizontal, LAParams

#SPACY
import spacy
from spacy.language import Language
from spacy_langdetect import LanguageDetector

#REDIS
import redis

url_redis = os.environ.get('REDIS_URL') or "redis://localhost:6379"
r = redis.from_url(url_redis) #could be an issue when it doesn' connect

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
    # Create the first language in english
    nlp = spacy.load("en_core_web_sm")
    # Add language detector to the pipeline
    nlp.add_pipe('language_detector', last=True)
    # Create the first doc just in order to check the language
    doc = nlp(block_to_test) # Time consuming
    # Guesses the language of the text
    lang_doc = doc._.language['language']
    # Checks the degree of accuracy of the previous check
    score_lang_doc = doc._.language['score']

    r.hset(id, "language",  lang_doc)
    r.hset(id, "score_language", score_lang_doc)

    # If the language isn't available use english
    language_available = lang_doc in available_languages["initials"]
    language = available_languages["object"][lang_doc] if language_available  else "en_core_web_sm"
    # create the final language according to our guess
    nlp = spacy.load(language)

    # Create blocks of text
    blocks_to_parse = create_blocks_to_analyze(text)
    text = None # save memory

    #This part takes approximately 50% of the global time when the doc is a pdf (tested with a pdf file of 1500 pages)
    percentage_taken = 50 if pdf else 90
    percentage_each_page = percentage_taken/len(blocks_to_parse)

    word_list = []
    number_of_chars = 0
    number_of_words = 0
    for block in blocks_to_parse:
      number_of_chars += len(block)

      doc = nlp(block)
      for token in doc:

        lemma = token.lemma_.lower()
        pos = token.pos_

        if pos in word_pos and not token.is_space:
          number_of_words += 1

          #By default we don't save stop words (most common words in a language)
          if token.is_stop and remove_stop_words: continue
          word_list.append((lemma, pos))

      counter = Counter(word_list)
      list_words_details = []
      for key in counter.keys():
        word_details = {}
        word_details["word"] = key[0] 
        word_details["pos"] = key[1]
        word_details["occurrence"] = counter[key]
        list_words_details.append(word_details)
      
      list_words_details.sort(reverse=True, key=sort_word_arr)

      word_counter = {
        "number_of_chars": number_of_chars,
        "number_of_words": number_of_words,
        "word_counter": list_words_details
      }

      previous_percentage = float(r.hgetall(id)[b"progression"].decode("ascii"))
      new_progression = previous_percentage + percentage_each_page
      r.hset(id, "progression", new_progression)


    r.hset(id, "counter", json.dumps(word_counter))
    r.hset(id, "progression", 100)
    return True
  except Exception as e:
    r.hset(id, "error", b"True")
    r.hset(id, "message", e)
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
      new_progression = float(r.hgetall(id)[b"progression"].decode("ascii")) + percentage_each_page
      r.hset(id, "progression", new_progression)
    return listLines
  
  except Exception as e:
    r.hset(id, "error", b"True")
    r.hset(id, "message", e)
    return False

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['GET', 'POST', 'DELETE'],
    allow_headers=['*'],
)

async def launch_process(id, file, stopW, txt):
  all_good = True
  try:
    if file:
      type_of_file = file.content_type
      content = await file.read()
             
      if type_of_file == 'application/pdf':

        text_pdf = await run_in_threadpool(lambda: convert_pdf_to_text(content, id))
        all_good = await run_in_threadpool(lambda: process_text(text_pdf, id, stopW, True))

      elif type_of_file == 'text/plain':
        content = content.decode("utf-8")
        max_size_blocks = 15000
        # If the text is too large
        content = await run_in_threadpool(lambda: split_large_text(content, max_size_blocks))
        all_good = await run_in_threadpool(lambda: process_text(content, id, stopW, False))

      else: raise Exception("The file is neither a .pdf nor a .txt file")

    # if we don't have to read a file
    else:
      if txt: all_good = await run_in_threadpool(lambda: process_text([txt], id, stopW, False))
      else: raise Exception("Le texte est vide...")

    if not all_good: raise Exception("Problème lors de l'analyse du texte")

  except Exception as e:
    r.hset(id, "error", b"True")
    r.hset(id, "message", e)


@app.post("/", status_code=202)
def read_root(
  background_tasks: BackgroundTasks,
  file: Optional[UploadFile] = File(None), 
  stopWords: Optional[bool] = Form(True),
  text: Optional[str] = Form(None),
):
  task_id = str(uuid.uuid4())
  r.hmset(task_id, {"progression": 5, "error": b"False", "time": str(datetime.now())})
  try:
    background_tasks.add_task(launch_process, task_id, file, stopWords, text)
    return { "id": task_id, "success": True }
  except:
    r.delete(task_id)
    detail_http={ "id": task_id, "success": False }
    raise HTTPException(status_code=400, detail=detail_http)


@app.get("/polling/{task_id}", status_code=200)
def polling(task_id: str, response: Response):
  response.headers['Connection'] = 'close'
  try:
    rep = {"id": task_id}

    if r.hgetall(task_id)[b"error"].decode("ascii") == 'True': 
      raise Exception('An error has occured')

    progression = float(r.hgetall(task_id)[b"progression"].decode("ascii"))
    rep["progression"] = progression
    if progression >= 100:  # could be ==
      rep["finish"] = True
    else:
      rep["finish"] = False

    rep["success"] = True

  except Exception as e:
    r.hset(task_id, "error", b"True")
    r.hset(task_id, "message", e)
    rep["success"] = False
    rep["message"] = "An error has occured while retrieving the data"
    raise HTTPException(status_code=400, detail=rep)

  return rep

@app.delete("/unsuccessful-polling/{task_id}")
def unsuccessful_polling(task_id: str):
  try:
    r.delete(task_id)
  except Exception:
    raise HTTPException(status_code=400, detail={"success": False}) 
  return {"success": True}

@app.get("/successful-polling/{task_id}")
def polling(task_id: str):
  try:
    rep = {"success": True}
    rep["stats"] = r.hgetall(task_id)
    rep["stats"][b"counter"] = json.loads(r.hgetall(task_id)[b"counter"]) #format the data

    r.delete(task_id)
  except Exception:
    raise HTTPException(status_code=400, detail={"success": False})
  return rep

setInterval(3600, remove_old_tasks, r) #Every hour
