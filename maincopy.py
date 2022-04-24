from asyncore import read
from typing import Optional
from xmlrpc.client import Boolean
from pydantic import BaseModel

import json

import spacy
from spacy.language import Language
from spacy_langdetect import LanguageDetector

stopwords = json.loads(open('./stopwords.json', mode = 'r', encoding='utf-8').read())

punctuation = ['.', ',', ';', ':', '!', '?', '-', '_', '"', '#', '`', '\\', '/', ')', '(', '&']

def process_text(text, use_stop_words = True):
  # https://stackoverflow.com/questions/66712753/how-to-use-languagedetector-from-spacy-langdetect-package
  @Language.factory("language_detector")
  def get_lang_detector(nlp, name):
    return LanguageDetector()

  # create the first language in english
  nlp_en = spacy.load("en_core_web_sm")
  # add language detector to the pipeline
  nlp_en.add_pipe('language_detector', last=True)
  # create the first doc just in order to check the language
  doc = nlp_en(text)
  # Guess the language of the text
  lang_doc = doc._.language['language']
  # Check the degree of accuracy of the previous check
  score_lang_doc = doc._.language['score']

  # Available languages
  languages = {
  "en": "en_core_web_sm",
  "fr": "fr_core_news_sm",
  "de": "de_core_news_sm",
  "es": "es_core_news_sm"
  }

  language = languages[lang_doc]
  # create the final language according to our guess
  nlp = spacy.load(language)
  # Create the final doc
  doc = nlp(text)

  stop_words = stopwords[lang_doc]

  word_counter = {}

  for token in doc:
    lemma = token.lemma_.lower()
    if lemma in punctuation: continue
    if lemma in stop_words: continue
    if lemma in word_counter: 
      word_counter[lemma] = word_counter[lemma] + 1
    else:
      word_counter[lemma] = 1

  return word_counter



def convert_pdf_to_txt2(file):
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.converter import TextConverter
    from pdfminer.layout import LAParams
    from pdfminer.pdfpage import PDFPage
    from io import BytesIO, StringIO
    rsrcmgr = PDFResourceManager()
    retstr = StringIO
    laparams = LAParams()
    device = TextConverter(rsrcmgr, retstr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    number = 0
    for page in PDFPage.get_pages(file):
        number = number + 1
        interpreter.process_page(page)

    text = retstr.getvalue()
    print(text)
    device.close()
    retstr.close()
    return text


from pdfminer.layout import LTTextBoxHorizontal
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter, resolve1
from pdfminer.pdfdocument import PDFDocument
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
from io import BytesIO

def convert_pdf_to_text(file):

  #Convert file into an in memory binary file 
  # file = BytesIO(file)

  # GET THE NUMBER OF PAGES
  parser = PDFParser(file)
  parsed_document = PDFDocument(parser)
  number_of_pages = resolve1(parsed_document.catalog['Pages'])['Count']
  
  rsrcmgr = PDFResourceManager()
  laparams = LAParams()
  device = PDFPageAggregator(rsrcmgr, laparams=laparams)
  interpreter = PDFPageInterpreter(rsrcmgr, device)

  listLines = ''
  
  for page in PDFPage.get_pages(file):
    interpreter.process_page(page)
    # receive the LTPage object for the page.
    layout = device.get_result()
    for element in layout:
      if isinstance(element, LTTextBoxHorizontal):
        page_text  = element.get_text().strip()
        listLines = listLines + '\n' + page_text

  return listLines


from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3000']
)

@app.post("/")
async def read_root(
  file: Optional[UploadFile] = File(None), 
  stopWords: Optional[bool] = Form(True),
  text: Optional[str] = Form(None)
):

  result_words = None

  # if we have to read a file
  if file:
    type_of_file = file.content_type
    content = await file.read()
    if type_of_file == 'application/pdf':
      text_pdf = convert_pdf_to_text(file)
      result_words = process_text(text_pdf, stopWords)
    elif type_of_file == 'text/plain':
      result_words = process_text(content, stopWords)
    else:
      pass
      # Throw error

  # if we don't have to read a file
  else:
    if text:
      result_words = process_text(text, stopWords)
    else:
      pass
      # Throw error

  
  return result_words
  # return body


# print((list(nlp.vocab.strings)))