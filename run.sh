
#Aktiver VENV
source ../venv/bin/activate


#Kjør serveren
export GEN_BACKEND=ollama
export OLLAMA_MODEL="deepseek-r1:8b"
export OLLAMA_URL="http://127.0.0.1:11434/api/chat"
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000 --reload



#Norsk tekst for test#1
#curl -X POST "http://127.0.0.1:8000/chat" \
 # -H "Content-Type: application/json" \
 # -d '{"message":"Hva skal jeg gjøre hvis det begynner å brenne på campus? Hvor er oppmøtestedet på Hamar? Svar kort med kilder.","temperature":0.2,"max_new_tokens":260}'


#Engelsk tekst for test#2
#curl -X POST "http://127.0.0.1:8000/chat" \
  # -H "Content-Type: application/json" \
  # -d '{"message":"What should I do if a fire breaks out on campus, and where is the assembly point at Hamar? Answer briefly with sources.","temperature":0.2,"max_new_tokens":260}'


#/Reindex: curl -X POST http://127.0.0.1:8000/reindex
