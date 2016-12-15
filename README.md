# parcell

`parcell` helps you to keep your work on your machine even when it needs to be
executed remotely. This is done by sending your project's code to one of your
beefy worker servers, running the code, and sending the results back. Multiple
tasks can be run in parallel and on different servers to balance the load. You
can keep improving your code on your machine without lag and get notified when
submitted tasks have been completed. No setup on the server side is required.

# Getting started

Clone the project via:

```bash
git clone https://github.com/JosuaKrause/parcell.git
cd parcell
```

And install the requirements:

```bash
git submodule update --init --recursive
pip install -r requirements.txt
```

Then start `parcell` for the first time:

```bash
python server.py
```

And browse to `http://localhost:8080/parcell/`.
You should see an empty "Select project" screen.
Stop `parcell` by typing `quit` in the terminal or pressing `CTRL-C`.

# Adding a server

Locate the `server` folder in your `parcell` directory.
Add a file `SERVERNAME.json` describing your server:

```javascript
{
  "hostname": "server1.foobar.com", // the server you want to access
  "username": "joe", // your username on the server
  "needs_pw": true, // whether you need to type a password to connect
  "tunnel": "joe@connect.foobar.com", // optional server for tunneling the connection
  "tunnel_port": 11111, // local port to tunnel through (only if tunneling)
  "needs_tunnel_pw": true  // whether you need to type a password to tunnel (only if tunneling)
}
```

It is recommended to restart `parcell` (e.g., by typing `restart`) after adding
a new server. If all your servers have the same password you can start `parcell`
with `python server.py --reuse-pw` to only type one password.

# Setting up a project

Locate the `project` folder in your `parcell` directory.
Add a file `PROJECTNAME.json` describing your project:

```javascript
{
  "local": "~/projects/awesome", // the path to your local project folder
  "cmd": "python run.py", // the command that runs your project
  "env": "linux", // the server environment (located in the env/ folder)
  "servers": [ // a list of servers (the SERVERNAME of the server description)
    "server1",
    "server2",
    "server3"
  ]
}
```
