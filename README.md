# voter
A simple web app for anonymous voting in a classroom.

To run this in Windows...

```cmd
py -m venv venv
venv\Scripts\pip install flask pymongo qrcode[pil] requests authlib
set MONGO_DB=voter
set MONGO_URL=mongodb://kubla.redbrick.xyz
set CLIENT_ID=OexMrdtxjRHb9L7TpjAysVDCZ0lZF5pI
set AUTH0_DOMAIN=faat.auth0.com
set CLIENT_SECRET=secret-goes-here
set FLASK_APP=voteapp.py
set FLASK_ENV=development
venv\Scripts\flask.exe run
```
