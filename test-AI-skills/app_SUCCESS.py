from flask import Flask, request, jsonify, send_file
import requests
import webbrowser
import psutil
import threading
import time
import asyncio
import aiohttp
from collections import defaultdict
from quart import Quart, request, jsonify, send_file
import hypercorn.asyncio
import logging
from quart_cors import cors
from datetime import datetime
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app = cors(app, allow_origin="*")

# API Configuration
GROK_API = "https://api.x.ai/v1/chat/completions"
GROK_API_KEY = "xai-uqlXMG81lvAEDf7YMwvm5eF9sDg4yPuqU6dPyECSwDoWgWZGtgoZ67B2QS6T8QHWRb1OWibpGYi0ulkm"

HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {GROK_API_KEY}'
}

# Simple in-memory storage
results_history = defaultdict(list)

def get_server_stats():
    process = psutil.Process()
    return {
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': process.memory_percent(),
        'connections': len(process.net_connections()),
        'threads': process.num_threads()
    }

async def get_ollama_stats():
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(GROK_API, headers=HEADERS, json={
                "model": "grok-2-latest",
                "messages": [{"role": "system", "content": "test"}],
                "stream": False
            }) as response:
                if response.status == 200:
                    return {
                        'status': 'connected',
                        'active_model': 'grok-2-latest',
                        'response_time_ms': 0,
                        'api_status': 'healthy'
                    }
                else:
                    return {
                        'status': 'error',
                        'active_model': 'grok-2-latest',
                        'response_time_ms': 0,
                        'api_status': 'error'
                    }
    except Exception as e:
        return {
            'status': 'error',
            'active_model': 'grok-2-latest',
            'response_time_ms': 0,
            'api_status': f'error: {str(e)}'
        }

async def get_ai_response(message, ctx_length):
    start_time = time.time()
    
    config = {
        "messages": [
            {"role": "system", "content": "You are a test assistant."},
            {"role": "user", "content": message}
        ],
        "model": "grok-2-latest",
        "stream": False,
        "temperature": 0
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROK_API, headers=HEADERS, json=config) as response:
                if response.status == 200:
                    result = await response.json()
                    response_time = (time.time() - start_time) * 1000
                    ai_response = result["choices"][0]["message"]["content"]
                    
                    return {
                        "response": ai_response,
                        "response_time_ms": round(response_time, 2),
                        "context_length": ctx_length
                    }
                else:
                    error_text = await response.text()
                    return {
                        "error": f"API Error: {error_text}",
                        "response_time_ms": 0,
                        "context_length": ctx_length
                    }
    except Exception as e:
        return {
            "error": str(e),
            "response_time_ms": 0,
            "context_length": ctx_length
        }

@app.route('/chat', methods=['POST'])
async def chat():
    try:
        data = await request.get_json()
        message = data.get('message', '').strip()
        context_lengths = data.get('contextLengths', [4096, 2048, 1024])
        
        if not message:
            return jsonify({"error": "Empty message"}), 400
            
        responses = []
        for ctx_length in context_lengths:
            response = await get_ai_response(message, ctx_length)
            responses.append(response)
            
            if 'error' not in response:
                key = f"ctx_{ctx_length}"
                results_history[key].append({
                    'response_time': response['response_time_ms'],
                    'response': response['response']
                })
            
            await asyncio.sleep(1)
            
        return jsonify({
            "responses": responses,
            "history": {
                'results': dict(results_history)
            }
        })
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/stats')
async def stats():
    return jsonify({
        'server': get_server_stats(),
        'ollama': await get_ollama_stats()
    })

@app.route('/history')
async def history():
    return jsonify({
        'results': dict(results_history)
    })

@app.route('/')
async def home():
    return await send_file('index.html')

@app.route('/generate-report', methods=['POST'])
async def generate_report():
    try:
        data = await request.get_json()
        question = data.get('question', '')
        responses = data.get('responses', [])
        
        # Ensure reports directory exists
        os.makedirs('reports', exist_ok=True)
        
        # Generate unique filename
        filename = f"reports/report_{int(time.time())}.txt"
        
        # Create report content
        report_content = f"""AI Response Report
Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Question: {question}

"""
        for response in responses:
            report_content += f"""
Context Length: {response['context_length']}
Response Time: {response['response_time_ms']}ms
Response: {response['response']}
----------------------------------------
"""
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        # Send the file
        return await send_file(filename, as_attachment=True, mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://localhost:8000')
    logger.info("Browser opened automatically")

if __name__ == '__main__':
    threading.Thread(target=open_browser, daemon=True).start()
    logger.info("Starting server at http://localhost:8000")
    asyncio.run(hypercorn.asyncio.serve(app, hypercorn.Config().from_mapping({
        "bind": ["localhost:8000"],
        "workers": 1
    }))) 