
*****
Setup
*****

Download
########

Go to the project page on GitHub and download the
`latest release <https://github.com/jonaswinkler/paperless-ng/releases>`_.
There are multiple options available.

*   Download the dockerfiles archive if you want to pull paperless from
    Docker Hub.

*   Download the dist archive and extract it if you want to build the docker image
    yourself or want to install paperless without docker.

.. hint::

    In contrast to paperless, the recommended way to get and update paperless-ng
    is not to pull the entire git repository. Paperless-ng includes artifacts
    that need to be compiled, and that's already done for you in the release.

.. admonition:: Want to try out paperless-ng before migrating?

    The release contains a file ``.env`` which sets the docker-compose project
    name to "paperless", which is the same as before and instructs docker-compose
    to reuse and upgrade your paperless volumes.

    Just rename the project name in that file to anything else and docker-compose
    will create fresh volumes for you!


Overview of Paperless-ng
########################

Compared to paperless, paperless-ng works a little different under the hood and has
more moving parts that work together. While this increases the complexity of
the system, it also brings many benefits.

Paperless consists of the following components:

*   **The webserver:** This is pretty much the same as in paperless. It serves
    the administration pages, the API, and the new frontend. This is the main
    tool you'll be using to interact with paperless. You may start the webserver
    with

    .. code:: shell-session

        $ cd /path/to/paperless/src/
        $ pipenv run gunicorn -c /usr/src/paperless/gunicorn.conf.py -b 0.0.0.0:8000 paperless.wsgi

    or by any other means such as Apache ``mod_wsgi``.

*   **The consumer:** This is what watches your consumption folder for documents.
    However, the consumer itself does not consume really consume your documents anymore.
    It rather notifies a task processor that a new file is ready for consumption.
    I suppose it should be named differently.
    This also used to check your emails, but that's now gone elsewhere as well.

    Start the consumer with the management command ``document_consumer``:

    .. code:: shell-session

        $ cd /path/to/paperless/src/
        $ pipenv run python3 manage.py document_consumer

    .. _setup-task_processor:

*   **The task processor:** Paperless relies on `Django Q <https://django-q.readthedocs.io/en/latest/>`_
    for doing much of the heavy lifting. This is a task queue that accepts tasks from
    multiple sources and processes tasks in parallel. It also comes with a scheduler that executes
    certain commands periodically.

    This task processor is responsible for:

    *   Consuming documents. When the consumer finds new documents, it notifies the task processor to
        start a consumption task.
    *   Consuming emails. It periodically checks your configured accounts for new mails and
        produces consumption tasks for any documents it finds.
    *   The task processor also performs the consumption of any documents you upload through
        the web interface.
    *   Maintain the search index and the automatic matching algorithm. These are things that paperless
        needs to do from time to time in order to operate properly.

    This allows paperless to process multiple documents from your consumption folder in parallel! On
    a modern multi core system, consumption with full ocr is blazing fast.

    The task processor comes with a built-in admin interface that you can use to see whenever any of the
    tasks fail and inspect the errors (i.e., wrong email credentials, errors during consuming a specific
    file, etc).

    You may start the task processor by executing:

    .. code:: shell-session

        $ cd /path/to/paperless/src/
        $ pipenv run python3 manage.py qcluster

*   A `redis <https://redis.io/>`_ message broker: This is a really lightweight service that is responsible
    for getting the tasks from the webserver and consumer to the task scheduler. These run in different
    processes (maybe even on different machines!), and therefore, this is necessary.

*   Optional: A database server. Paperless supports both PostgreSQL and SQLite for storing its data.


Installation
############

You can go multiple routes with setting up and running Paperless:

* The `docker route`_
* The `bare metal route`_

The `docker route`_ is quick & easy. This is the recommended route. This configures all the stuff
from above automatically so that it just works and uses sensible defaults for all configuration options.

The `bare metal route`_ is more complicated to setup but makes it easier
should you want to contribute some code back. You need to configure and
run the above mentioned components yourself.

Docker Route
============

1.  Install `Docker`_ and `docker-compose`_. [#compose]_

    .. caution::

        If you want to use the included ``docker-compose.*.yml`` file, you
        need to have at least Docker version **17.09.0** and docker-compose
        version **1.17.0**.

        See the `Docker installation guide`_ on how to install the current
        version of Docker for your operating system or Linux distribution of
        choice. To get an up-to-date version of docker-compose, follow the
        `docker-compose installation guide`_ if your package repository doesn't
        include it.

        .. _Docker installation guide: https://docs.docker.com/engine/installation/
        .. _docker-compose installation guide: https://docs.docker.com/compose/install/

2.  Copy either ``docker-compose.sqlite.yml`` or ``docker-compose.postgres.yml`` to
    ``docker-compose.yml``, depending on which database backend you want to use.

    .. hint::

        For new installations, it is recommended to use PostgreSQL as the database
        backend.

2.  Modify ``docker-compose.yml`` to your preferences. You may want to change the path
    to the consumption directory in this file. Find the line that specifies where
    to mount the consumption directory:

    .. code::

        - ./consume:/usr/src/paperless/consume

    Replace the part BEFORE the colon with a local directory of your choice:

    .. code::

        - /home/jonaswinkler/paperless-inbox:/usr/src/paperless/consume

    Don't change the part after the colon or paperless wont find your documents.


3.  Modify ``docker-compose.env``, following the comments in the file. The
    most important change is to set ``USERMAP_UID`` and ``USERMAP_GID``
    to the uid and gid of your user on the host system. This ensures that
    both the docker container and you on the host machine have write access
    to the consumption directory. If your UID and GID on the host system is
    1000 (the default for the first normal user on most systems), it will
    work out of the box without any modifications.

    .. note::

        You can use any settings from the file ``paperless.conf`` in this file.
        Have a look at :ref:`configuration` to see whats available.

4.  Run ``docker-compose up -d``. This will create and start the necessary
    containers. This will also build the image of paperless if you grabbed the
    source archive.

5.  To be able to login, you will need a super user. To create it, execute the
    following command:

    .. code-block:: shell-session

        $ docker-compose run --rm webserver createsuperuser

    This will prompt you to set a username, an optional e-mail address and
    finally a password.

6.  The default ``docker-compose.yml`` exports the webserver on your local port
    8000. If you haven't adapted this, you should now be able to visit your
    Paperless instance at ``http://127.0.0.1:8000``. You can login with the
    user and password you just created.

.. _Docker: https://www.docker.com/
.. _docker-compose: https://docs.docker.com/compose/install/

.. [#compose] You of course don't have to use docker-compose, but it
   simplifies deployment immensely. If you know your way around Docker, feel
   free to tinker around without using compose!


Bare Metal Route
================

.. warning::

    TBD. User docker for now.

Migration to paperless-ng
#########################

At its core, paperless-ng is still paperless and fully compatible. However, some
things have changed under the hood, so you need to adapt your setup depending on
how you installed paperless. The important things to keep in mind are as follows.

* Read the :ref:`changelog <paperless_changelog>` and take note of breaking changes.
* You should decide if you want to stick with SQLite or want to migrate your database
  to PostgreSQL. See :ref:`setup-sqlite_to_psql` for details on how to move your data from
  SQLite to PostgreSQL. Both work fine with paperless. However, if you already have a
  database server running for other services, you might as well use it for paperless as well.
* The task scheduler of paperless, which is used to execute periodic tasks
  such as email checking and maintenance, requires a `redis`_ message broker
  instance. The docker-compose route takes care of that.
* The layout of the folder structure for your documents and data remains the
  same, so you can just plug your old docker volumes into paperless-ng and
  expect it to find everything where it should be.

Migration to paperless-ng is then performed in a few simple steps:

1.  Stop paperless.

    .. code:: bash

        $ cd /path/to/current/paperless
        $ docker-compose down

2.  Do a backup for two purposes: If something goes wrong, you still have your
    data. Second, if you don't like paperless-ng, you can switch back to
    paperless.

3.  Download the latest release of paperless-ng. You can either go with the
    docker-compose files or use the archive to build the image yourself.
    You can either replace your current paperless folder or put paperless-ng
    in a different location.

    .. caution::

        The release include a ``.env`` file. This will set the
        project name for docker compose to ``paperless`` so that paperless-ng will
        automatically reuse your existing paperless volumes. When you start it, it
        will migrate your existing data. After that, your old paperless installation
        will be incompatible with the migrated volumes.

4.  Copy the ``docker-compose.sqlite.yml`` file to ``docker-compose.yml``.
    If you want to switch to PostgreSQL, do that after you migrated your existing
    SQLite database.

5.  Adjust ``docker-compose.yml`` and
    ``docker-compose.env`` to your needs.
    See `docker route`_ for details on which edits are advised.

6.  In order to find your existing documents with the new search feature, you need
    to invoke a one-time operation that will create the search index:

    .. code:: shell-session

        $ docker-compose run --rm webserver document_index reindex
    
    This will migrate your database and create the search index. After that,
    paperless will take care of maintaining the index by itself.

7.  Start paperless-ng.

    .. code:: bash

        $ docker-compose up -d

    This will run paperless in the background and automatically start it on system boot.

8.  Paperless installed a permanent redirect to ``admin/`` in your browser. This
    redirect is still in place and prevents access to the new UI. Clear
    browsing cache in order to fix this.

9.  Optionally, follow the instructions below to migrate your existing data to PostgreSQL.


.. _setup-sqlite_to_psql:

Moving data from SQLite to PostgreSQL
=====================================

Moving your data from SQLite to PostgreSQL is done via executing a series of django
management commands as below.

.. caution::

    Make sure that your SQLite database is migrated to the latest version.
    Starting paperless will make sure that this is the case. If your try to
    load data from an old database schema in SQLite into a newer database
    schema in PostgreSQL, you will run into trouble.

1.  Stop paperless, if it is running.
2.  Tell paperless to use PostgreSQL:

    a)  With docker, copy the provided ``docker-compose.postgres.yml`` file to
        ``docker-compose.yml``. Remember to adjust the consumption directory,
        if necessary.
    b)  Without docker, configure the database in your ``paperless.conf`` file.
        See :ref:`configuration` for details.

3.  Open a shell and initialize the database:

    a)  With docker, run the following command to open a shell within the paperless
        container:

        .. code:: shell-session

            $ cd /path/to/paperless
            $ docker-compose run --rm webserver /bin/bash
        
        This will launch the container and initialize the PostgreSQL database.
    
    b)  Without docker, open a shell in your virtual environment, switch to
        the ``src`` directory and create the database schema:

        .. code:: shell-session

            $ cd /path/to/paperless
            $ pipenv shell
            $ cd src
            $ python3 manage.py migrate
        
        This will not copy any data yet.

4.  Dump your data from SQLite:

    .. code:: shell-session

        $ python3 manage.py dumpdata --database=sqlite --exclude=contenttypes --exclude=auth.Permission > data.json
    
5.  Load your data into PostgreSQL:

    .. code:: shell-session

        $ python3 manage.py loaddata data.json

6.  Exit the shell.

    .. code:: shell-session

        $ exit

7.  Start paperless.


Moving back to paperless
========================

Lets say you migrated to Paperless-ng and used it for a while, but decided that
you don't like it and want to move back (If you do, send me a mail about what
part you didn't like!), you can totally do that with a few simple steps.

Paperless-ng modified the database schema slightly, however, these changes can
be reverted while keeping your current data, so that your current data will
be compatible with original Paperless.

Execute this:

.. code:: shell-session

    $ cd /path/to/paperless
    $ docker-compose run --rm webserver migrate documents 0023

Or without docker:

.. code:: shell-session

    $ cd /path/to/paperless/src
    $ python3 manage.py migrate documents 0023

After that, you need to clear your cookies (Paperless-ng comes with updated
dependencies that do cookie-processing differently) and probably your cache
as well.

.. _setup-less_powerful_devices:


Considerations for less powerful devices
########################################

Paperless runs on Raspberry Pi. However, some things are rather slow on the Pi and 
configuring some options in paperless can help improve performance immensely:

*   Stick with SQLite to save some resources.
*   Consider setting ``PAPERLESS_OCR_PAGES`` to 1, so that paperless will only OCR
    the first page of your documents.
*   ``PAPERLESS_TASK_WORKERS`` and ``PAPERLESS_THREADS_PER_WORKER`` are configured
    to use all cores. The Raspberry Pi models 3 and up have 4 cores, meaning that
    paperless will use 2 workers and 2 threads per worker. This may result in
    sluggish response times during consumption, so you might want to lower these
    settings (example: 2 workers and 1 thread to always have some computing power
    left for other tasks).
*   Keep ``PAPERLESS_OCR_ALWAYS`` at its default value 'false' and consider OCR'ing
    your documents before feeding them into paperless. Some scanners are able to
    do this!
*   Lower ``PAPERLESS_CONVERT_DENSITY`` from its default value 300 to 200. This
    will still result in rather accurate OCR, but will decrease consumption time
    by quite a bit.
*   Set ``PAPERLESS_OPTIMIZE_THUMBNAILS`` to 'false' if you want faster consumption
    times. Thumbnails will be about 20% larger.

For details, refer to :ref:`configuration`.

.. note::
    
    Updating the :ref:`automatic matching algorithm <advanced-automatic_matching>`
    takes quite a bit of time. However, the update mechanism checks if your
    data has changed before doing the heavy lifting. If you experience the 
    algorithm taking too much cpu time, consider changing the schedule in the
    admin interface to daily. You can also manually invoke the task
    by changing the date and time of the next run to today/now.

    The actual matching of the algorithm is fast and works on Raspberry Pi as 
    well as on any other device.



.. _redis: https://redis.io/
