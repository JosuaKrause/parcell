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
---------------

Install the project via:

.. code:: bash

    pip install parcell

Choose a working directory for your projects and ``cd`` into it.

Now run

.. code:: bash

    parcell add PROJECTNAME

where ``PROJECTNAME`` is the name of the project you want to create.
Follow all instructions until the script creates your project.

Then run

.. code:: bash

    parcell start

to start the web interface. Note that you can avoid retyping your passwords
for different servers using the ``--reuse-pw`` command line argument in
either command (given all the servers accept the same password).
Once the web interface is started you can interact with your project.
When finished you can stop ``parcell`` by typing ``quit`` in the
terminal or pressing ``CTRL-C``. Typing ``restart`` restarts the web interface.

Use

.. code:: bash

    parcell -h

or

.. code:: bash

    parcell COMMAND -h

to get further information about the command line capabilities.

Contributing
------------

Pull requests are highly appreciated :) Also, feel free to open
`issues <https://github.com/JosuaKrause/parcell/issues>`__ for any
questions or bugs you may encounter.

If you want to work on the code of ``parcell``. Set the project up as follows:

.. code:: bash

    git clone https://github.com/JosuaKrause/parcell.git
    cd parcell
    git submodule update --init --recursive
    pip install -e .

This way you need to call ``parcell`` via:

.. code:: bash

    python -m parcell ...
