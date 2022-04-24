import time, threading
from datetime import datetime, timedelta

# Same as js function
class setInterval :
    def __init__(self, interval, action, optional_arg = None) :
        self.interval=interval
        self.action=action
        self.optional_arg = optional_arg
        self.stopEvent=threading.Event()
        thread=threading.Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self) :
        nextTime=time.time()+self.interval
        # -100 comme j'aurais pu mettre n'importe quelle valeur négative
        while not self.stopEvent.wait(nextTime-time.time()) :
            nextTime+=self.interval
            self.action(self.optional_arg)  

    def cancel(self) :
        self.stopEvent.set()

#Splits the text if into several blocks if it is too large
#max_size_blocks allow us to choose the size of each block
#Optimisable
def split_large_text(text, max_size_blocks = 15000):
  t = text
  if len(t) > max_size_blocks:
    blocks = []
    block = ''
    while len(t) > max_size_blocks:
      block = t[0:max_size_blocks]
      split = t[max_size_blocks:].split('\n', 1)
      block += split[0]
      t = split[1]
      blocks.append(block)
      if len(t) < max_size_blocks: blocks.append(block)

    t = blocks

  else: t = [text]

  return t

# Split the text into blocks
# Join blocks of text in order to not analyze every block 1 by 1
# But rather 10 by 10
def create_blocks_to_analyze(text):
    blocks_to_parse = []
    length_blocks = len(text)
    iteration = 0 
    while iteration  < length_blocks:
        to_append = text[iteration:(iteration+10)]
        to_append = '\n'.join(to_append)
        blocks_to_parse.append(to_append)
        iteration += 10

    return blocks_to_parse 

available_languages = {
    "initials": ['en', 'fr', 'de', 'es'],
    #In the future I should use bigger pipeline (not sm)
    #Thus I could use alpha and oov attributes on the token
    "object": {
        "en": "en_core_web_sm",
        "fr": "fr_core_news_sm",
        "de": "de_core_news_sm",
        "es": "es_core_news_sm"
    }
}

def read_redis_db(db):
    keys = db.keys('*')
    store = {}
    
    for key in keys:
        val = None
        type_key = db.type(key).decode('ascii')
        if type_key == "string":
            val = db.get(key)
        if type_key == "hash":
            val = db.hgetall(key)
        if type_key == "zset":
            val = db.zrange(key, 0, -1)
        if type_key == "list":
            val = db.lrange(key, 0, -1)
        if type_key == "set":
            val = db.smembers(key)
        store[key.decode('ascii')] = val

    print(store)

def remove_old_tasks(db):
    keys = db.keys('*')

    for key in keys:
        type_key = db.type(key).decode('ascii')
        if type_key == "hash":
            time_task = db.hgetall(key)[b"time"].decode('ascii')
            # convert from string back to datetime
            time_task = datetime.strptime(time_task, "%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.now()
            delta_time = current_time - time_task
            #convert delta time to minutes
            delta_time = delta_time.total_seconds() / 3600 # 60 seconds * 60 minutes
            # If the task has been stored during more than 4 hours remove it
            if delta_time > 4:
                db.delete(key)



        

    