"""Isolated product server for Task B's browser smoke test; never reads user runtime."""
import asyncio
import sys
import uvicorn
from aiqa.api.app import create_app
from aiqa.config import load_settings

if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app=create_app(load_settings({'AIQA_HOST':'127.0.0.1','AIQA_PORT':sys.argv[2],'AIQA_RUNTIME_ROOT':sys.argv[1]}))
    uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]),loop='asyncio',log_level='warning')
