# Troubleshooting

## No files are added by the consumer

Check for the following issues:

-   Ensure that the directory you're putting your documents in is the
    folder paperless is watching. With docker, this setting is performed
    in the `docker-compose.yml` file. Without Docker, look at the
    `CONSUMPTION_DIR` setting. Don't adjust this setting if you're
    using docker.

-   Ensure that redis is up and running. Paperless does its task
    processing asynchronously, and for documents to arrive at the task
    processor, it needs redis to run.

-   Ensure that the task processor is running. Docker does this
    automatically. Manually invoke the task processor by executing

    ```shell-session
    celery --app paperless worker
    ```

-   Look at the output of paperless and inspect it for any errors.

-   Go to the admin interface, and check if there are failed tasks. If
    so, the tasks will contain an error message.

## Consumer warns `OCR for XX failed`

If you find the OCR accuracy to be too low, and/or the document consumer
warns that
`OCR for XX failed, but we're going to stick with what we've got since FORGIVING_OCR is enabled`,
then you might need to install the [Tesseract language
files](https://packages.ubuntu.com/search?keywords=tesseract-ocr)
marching your document's languages.

As an example, if you are running Paperless-ngx from any Ubuntu or
Debian box, and your documents are written in Spanish you may need to
run:

    apt-get install -y tesseract-ocr-spa

## Consumer fails to pickup any new files

If you notice that the consumer will only pickup files in the
consumption directory at startup, but won't find any other files added
later, you will need to enable filesystem polling with the configuration
option [`PAPERLESS_CONSUMER_POLLING`](configuration.md#PAPERLESS_CONSUMER_POLLING).

This will disable listening to filesystem changes with inotify and
paperless will manually check the consumption directory for changes
instead.

## Paperless always redirects to /admin

You probably had the old paperless installed at some point. Paperless
installed a permanent redirect to /admin in your browser, and you need
to clear your browsing data / cache to fix that.

## Operation not permitted

You might see errors such as:

```shell-session
chown: changing ownership of '../export': Operation not permitted
```

The container tries to set file ownership on the listed directories.
This is required so that the user running paperless inside docker has
write permissions to these folders. This happens when pointing these
directories to NFS shares, for example.

Ensure that `chown` is possible on these directories.

## Classifier error: No training data available

This indicates that the Auto matching algorithm found no documents to
learn from. This may have two reasons:

-   You don't use the Auto matching algorithm: The error can be safely
    ignored in this case.
-   You are using the Auto matching algorithm: The classifier explicitly
    excludes documents with Inbox tags. Verify that there are documents
    in your archive without inbox tags. The algorithm will only learn
    from documents not in your inbox.

## UserWarning in sklearn on every single document

You may encounter warnings like this:

```
/usr/local/lib/python3.7/site-packages/sklearn/base.py:315:
UserWarning: Trying to unpickle estimator CountVectorizer from version 0.23.2 when using version 0.24.0.
This might lead to breaking code or invalid results. Use at your own risk.
```

This happens when certain dependencies of paperless that are responsible
for the auto matching algorithm are updated. After updating these, your
current training data _might_ not be compatible anymore. This can be
ignored in most cases. This warning will disappear automatically when
paperless updates the training data.

If you want to get rid of the warning or actually experience issues with
automatic matching, delete the file `classification_model.pickle` in the
data directory and let paperless recreate it.

## 504 Server Error: Gateway Timeout when adding Office documents

You may experience these errors when using the optional TIKA
integration:

```
requests.exceptions.HTTPError: 504 Server Error: Gateway Timeout for url: http://gotenberg:3000/forms/libreoffice/convert
```

Gotenberg is a server that converts Office documents into PDF documents
and has a default timeout of 30 seconds. When conversion takes longer,
Gotenberg raises this error.

You can increase the timeout by configuring a command flag for Gotenberg
(see also [here](https://gotenberg.dev/docs/modules/api#properties)). If
using Docker Compose, this is achieved by the following configuration
change in the `docker-compose.yml` file:

```yaml
# The gotenberg chromium route is used to convert .eml files. We do not
# want to allow external content like tracking pixels or even javascript.
command:
    - 'gotenberg'
    - '--chromium-disable-javascript=true'
    - '--chromium-allow-list=file:///tmp/.*'
    - '--api-timeout=60'
```

## Permission denied errors in the consumption directory

You might encounter errors such as:

```shell-session
The following error occurred while consuming document.pdf: [Errno 13] Permission denied: '/usr/src/paperless/src/../consume/document.pdf'
```

This happens when paperless does not have permission to delete files
inside the consumption directory. Ensure that `USERMAP_UID` and
`USERMAP_GID` are set to the user id and group id you use on the host
operating system, if these are different from `1000`. See [Docker setup](setup.md#docker).

Also ensure that you are able to read and write to the consumption
directory on the host.

## OSError: \[Errno 19\] No such device when consuming files

If you experience errors such as:

```shell-session
File "/usr/local/lib/python3.7/site-packages/whoosh/codec/base.py", line 570, in open_compound_file
return CompoundStorage(dbfile, use_mmap=storage.supports_mmap)
File "/usr/local/lib/python3.7/site-packages/whoosh/filedb/compound.py", line 75, in __init__
self._source = mmap.mmap(fileno, 0, access=mmap.ACCESS_READ)
OSError: [Errno 19] No such device

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
File "/usr/local/lib/python3.7/site-packages/django_q/cluster.py", line 436, in worker
res = f(*task["args"], **task["kwargs"])
File "/usr/src/paperless/src/documents/tasks.py", line 73, in consume_file
override_tag_ids=override_tag_ids)
File "/usr/src/paperless/src/documents/consumer.py", line 271, in try_consume_file
raise ConsumerError(e)
```

Paperless uses a search index to provide better and faster full text
searching. This search index is stored inside the `data` folder. The
search index uses memory-mapped files (mmap). The above error indicates
that paperless was unable to create and open these files.

This happens when you're trying to store the data directory on certain
file systems (mostly network shares) that don't support memory-mapped
files.

## Web-UI stuck at "Loading\..."

This might have multiple reasons.

1.  If you built the docker image yourself or deployed using the bare
    metal route, make sure that there are files in
    `<paperless-root>/static/frontend/<lang-code>/`. If there are no
    files, make sure that you executed `collectstatic` successfully,
    either manually or as part of the docker image build.

    If the front end is still missing, make sure that the front end is
    compiled (files present in `src/documents/static/frontend`). If it
    is not, you need to compile the front end yourself or download the
    release archive instead of cloning the repository.

## Error while reading metadata

You might find messages like these in your log files:

```
[WARNING] [paperless.parsing.tesseract] Error while reading metadata
```

This indicates that paperless failed to read PDF metadata from one of
your documents. This happens when you open the affected documents in
paperless for editing. Paperless will continue to work, and will simply
not show the invalid metadata.

## Consumer fails with a FileNotFoundError

You might find messages like these in your log files:

```
[ERROR] [paperless.consumer] Error while consuming document SCN_0001.pdf: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ocrmypdf.io.yhk3zbv0/origin.pdf'
Traceback (most recent call last):
  File "/app/paperless/src/paperless_tesseract/parsers.py", line 261, in parse
    ocrmypdf.ocr(**args)
  File "/usr/local/lib/python3.8/dist-packages/ocrmypdf/api.py", line 337, in ocr
    return run_pipeline(options=options, plugin_manager=plugin_manager, api=True)
  File "/usr/local/lib/python3.8/dist-packages/ocrmypdf/_sync.py", line 385, in run_pipeline
    exec_concurrent(context, executor)
  File "/usr/local/lib/python3.8/dist-packages/ocrmypdf/_sync.py", line 302, in exec_concurrent
    pdf = post_process(pdf, context, executor)
  File "/usr/local/lib/python3.8/dist-packages/ocrmypdf/_sync.py", line 235, in post_process
    pdf_out = metadata_fixup(pdf_out, context)
  File "/usr/local/lib/python3.8/dist-packages/ocrmypdf/_pipeline.py", line 798, in metadata_fixup
    with pikepdf.open(context.origin) as original, pikepdf.open(working_file) as pdf:
  File "/usr/local/lib/python3.8/dist-packages/pikepdf/_methods.py", line 923, in open
    pdf = Pdf._open(
FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ocrmypdf.io.yhk3zbv0/origin.pdf'
```

This probably indicates paperless tried to consume the same file twice.
This can happen for a number of reasons, depending on how documents are
placed into the consume folder. If paperless is using inotify (the
default) to check for documents, try adjusting the
[inotify configuration](configuration.md#inotify). If polling is enabled, try adjusting the
[polling configuration](configuration.md#polling).

## Consumer fails waiting for file to remain unmodified.

You might find messages like these in your log files:

```
[ERROR] [paperless.management.consumer] Timeout while waiting on file /usr/src/paperless/src/../consume/SCN_0001.pdf to remain unmodified.
```

This indicates paperless timed out while waiting for the file to be
completely written to the consume folder. Adjusting
[polling configuration](configuration.md#polling) values should resolve the issue.

!!! note

    The user will need to manually move the file out of the consume folder
    and back in, for the initial failing file to be consumed.

## Consumer fails reporting "OS reports file as busy still".

You might find messages like these in your log files:

```
[WARNING] [paperless.management.consumer] Not consuming file /usr/src/paperless/src/../consume/SCN_0001.pdf: OS reports file as busy still
```

This indicates paperless was unable to open the file, as the OS reported
the file as still being in use. To prevent a crash, paperless did not
try to consume the file. If paperless is using inotify (the default) to
check for documents, try adjusting the
[inotify configuration](configuration.md#inotify). If polling is enabled, try adjusting the
[polling configuration](configuration.md#polling).

!!! note

    The user will need to manually move the file out of the consume folder
    and back in, for the initial failing file to be consumed.

## Log reports "Creating PaperlessTask failed".

You might find messages like these in your log files:

```
[ERROR] [paperless.management.consumer] Creating PaperlessTask failed: db locked
```

You are likely using an sqlite based installation, with an increased
number of workers and are running into sqlite's concurrency
limitations. Uploading or consuming multiple files at once results in
many workers attempting to access the database simultaneously.

Consider changing to the PostgreSQL database if you will be processing
many documents at once often. Otherwise, try tweaking the
[`PAPERLESS_DB_TIMEOUT`](configuration.md#PAPERLESS_DB_TIMEOUT) setting to allow more time for the database to
unlock. This may have minor performance implications.

## granian fails to start with "is not a valid port number"

You are likely running using Kubernetes, which automatically creates an
environment variable named `${serviceName}_PORT`. This is
the same environment variable which is used by Paperless to optionally
change the port granian listens on.

To fix this, set [`PAPERLESS_PORT`](configuration.md#PAPERLESS_PORT) again to your desired port, or the
default of 8000.

## Database Warns about unique constraint "documents_tag_name_uniq

You may see database log lines like:

```
ERROR:  duplicate key value violates unique constraint "documents_tag_name_uniq"
DETAIL:  Key (name)=(NameF) already exists.
STATEMENT:  INSERT INTO "documents_tag" ("owner_id", "name", "match", "matching_algorithm", "is_insensitive", "color", "is_inbox_tag") VALUES (NULL, 'NameF', '', 1, true, '#a6cee3', false) RETURNING "documents_tag"."id"
```

This can happen during heavy consumption when using polling. Paperless will handle it correctly and the file
will still be consumed

## Consumption fails with "Ghostscript PDF/A rendering failed"

Newer versions of OCRmyPDF will fail if it encounters errors during processing.
This is intentional as the output archive file may differ in unexpected or undesired
ways from the original. As the logs indicate, if you encounter this error you can set
`PAPERLESS_OCR_USER_ARGS: '{"continue_on_soft_render_error": true}'` to try to 'force'
processing documents with this issue.

## Logs show "possible incompatible database column" when deleting documents {#convert-uuid-field}

You may see errors when deleting documents like:

```
Data too long for column 'transaction_id' at row 1
```

This error can occur in installations which have upgraded from a version of Paperless-ngx that used Django 4 (Paperless-ngx versions prior to v2.13.0) with a MariaDB/MySQL database. Due to the backawards-incompatible change in Django 5, the column "documents_document.transaction_id" will need to be re-created, which can be done with a one-time run of the following management command:

```shell-session
$ python3 manage.py convert_mariadb_uuid
```

## Platform-Specific Deployment Troubleshooting

A user-maintained wiki page is available to help troubleshoot issues that may arise when trying to deploy Paperless-ngx on specific platforms, for example SELinux. Please see [the wiki](https://github.com/paperless-ngx/paperless-ngx/wiki/Platform%E2%80%90Specific-Troubleshooting).
