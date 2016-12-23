parcell
=======

``parcell`` helps you to keep your work on your machine even when it
needs to be executed remotely. This is done by sending your project's
code to one of your beefy worker servers, running the code, and sending
the results back. Multiple tasks can be run in parallel and on different
servers to balance the load. You can keep improving your code on your
machine without lag and get notified when submitted tasks have been
completed. No setup on the server side is required.

Getting started
===============

Install the project via:

.. code:: bash

    pip install parcell

Then start ``parcell`` for the first time in the working directory of your choice:

.. code:: bash

    parcell

Note that ``parcell`` uses your current working directory to locate your
projects and servers so make sure you are in the same directory every
time you start it. After starting ``parcell`` browses to
``http://localhost:8000/parcell/``. You should see an empty "Select
project" screen. Stop ``parcell`` by typing ``quit`` in the terminal or
pressing ``CTRL-C``. Add projects and servers as shown below. Then start
the server again. If everything worked you should see your projects.

Adding a server
===============

Locate the ``servers`` folder in your working directory. Add a file
``SERVERNAME.json`` describing your server:

.. code:: javascript

    {
      "hostname": "server1.foobar.com", // the server you want to access
      "username": "joe", // your username on the server
      "needs_pw": true, // whether you need to type a password to connect
      "tunnel": "joe@connect.foobar.com", // optional server for tunneling the connection
      "tunnel_port": 11111, // local port to tunnel through (only if tunneling) -- must be unique for each server
      "needs_tunnel_pw": true  // whether you need to type a password to tunnel (only if tunneling)
    }

Note that JSON cannot contain comments!

It is recommended to restart ``parcell`` (e.g., by typing ``restart``)
after adding new servers. If all your servers have the same password you
can start ``parcell`` with ``python server.py --reuse-pw`` to only type
one password.

Setting up a project
====================

Locate the ``projects`` folder in your ``parcell`` directory. Add a file
``PROJECTNAME.json`` describing your project:

.. code:: javascript

    {
      "local": "~/projects/awesome", // the path to your local project folder (note that all contents of this folder and subfolders will be copied onto the server)
      "cmd": "python run.py", // the command that runs your project
      "env": "linux", // the server environment (located in the env/ folder)
      "servers": [ // a list of servers (the SERVERNAME of the server description)
        "server1",
        "server2",
        "server3"
      ]
    }

Note that JSON cannot contain comments!
