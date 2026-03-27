# Translation RPC Service

Standalone translation RPC service for History RAG.

Copy this whole directory to the target server and run it from inside the directory.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python install_models.py
```

By default, `install_models.py` installs:

- `en:zh`
- `ja:zh`
- `ko:zh`

When a direct Argos package is unavailable, the service will try an English pivot path automatically.
For example, `ja:zh` may be installed and translated via `ja:en` + `en:zh`.

You can also install explicit pairs:

```bash
python install_models.py --pair en:zh --pair ja:zh --pair ko:zh
```

## Run

```bash
python server.py --host 0.0.0.0 --port 50052
```

You can also run it as a module from the `backend` directory:

```bash
python -m services.translation_rpc.server --host 0.0.0.0 --port 50052
```

## Included Files

- `server.py`: standalone gRPC server entry
- `install_models.py`: model installer
- `translation_runtime.py`: Argos translation runtime
- `translation.proto`: protocol source
- `translation_pb2.py` and `translation_pb2_grpc.py`: generated Python stubs
