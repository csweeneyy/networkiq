#!/usr/bin/env python3
"""
NetworkIQ - LinkedIn Network Analyzer
Run: python networkiq.py

Requirements: pip install flask requests
"""

import os
import json
import csv
import time
import re
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify
import requests

app = Flask(__name__)

# ============ CONFIGURATION ============
DATA_FILE = Path(__file__).parent / "networkiq_data.json"

def load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"connections": [], "api_keys": {"tavily": "", "gemini": ""}}

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))

# ============ CSV PARSING ============
def parse_linkedin_csv(file_path):
    """Parse LinkedIn Connections.csv, handling the Notes preamble."""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
    
    # Find header row (skip LinkedIn's Notes preamble)
    header_idx = 0
    for i, line in enumerate(lines):
        if 'first name' in line.lower() and 'last name' in line.lower():
            header_idx = i
            break
    
    connections = []
    reader = csv.DictReader(lines[header_idx:])
    
    for i, row in enumerate(reader):
        # Normalize keys to lowercase
        row = {k.lower().strip(): v for k, v in row.items()}
        
        conn = {
            "id": f"conn_{i}_{int(time.time()*1000)}",
            "firstName": row.get('first name', ''),
            "lastName": row.get('last name', ''),
            "email": row.get('email address', ''),
            "company": row.get('company', ''),
            "position": row.get('position', ''),
            "url": row.get('url', ''),
            "connectedOn": row.get('connected on', ''),
            "blurb": None,
            "enrichedAt": None,
            "category": None
        }
        
        if conn["firstName"] or conn["lastName"]:
            conn["category"] = categorize_connection(conn)
            connections.append(conn)
    
    return connections

def categorize_connection(conn):
    """Auto-categorize based on job title."""
    position = (conn.get('position') or '').lower()
    
    if re.search(r'founder|co-founder|cofounder|owner', position, re.I):
        return 'Founders'
    if re.search(r'^ceo|^cto|^cfo|^coo|^cmo|^cio|chief', position, re.I):
        return 'Executives'
    if re.search(r'^vp|vice president|director|head of', position, re.I):
        return 'Leadership'
    if re.search(r'recruit|talent|hr|human resource|people ops', position, re.I):
        return 'Recruiting'
    if re.search(r'investor|partner|vc|venture|capital|angel', position, re.I):
        return 'Investors'
    if re.search(r'engineer|developer|software|swe|sde|programmer|architect', position, re.I):
        return 'Engineering'
    if re.search(r'product|pm|program manager', position, re.I):
        return 'Product'
    if re.search(r'design|ux|ui|creative', position, re.I):
        return 'Design'
    if re.search(r'sales|account|business dev|bd', position, re.I):
        return 'Sales'
    if re.search(r'market|growth|brand|content|seo|social', position, re.I):
        return 'Marketing'
    if re.search(r'consult|advisor|strateg', position, re.I):
        return 'Consulting'
    if re.search(r'student|intern|university|college|phd|research', position, re.I):
        return 'Students'
    if re.search(r'analy|data|scientist', position, re.I):
        return 'Data'
    if re.search(r'finance|accounting|controller', position, re.I):
        return 'Finance'
    if re.search(r'legal|counsel|attorney|lawyer', position, re.I):
        return 'Legal'
    if re.search(r'operat|admin|office|assistant', position, re.I):
        return 'Operations'
    return 'Other'

# ============ API FUNCTIONS ============
def search_tavily(query, api_key):
    """Search using Tavily API."""
    response = requests.post(
        'https://api.tavily.com/search',
        json={
            'api_key': api_key,
            'query': query,
            'search_depth': 'basic',
            'max_results': 5,
            'include_answer': False,
            'include_raw_content': False
        },
        timeout=30
    )
    response.raise_for_status()
    return response.json()

def generate_blurb(search_results, person_name, api_key):
    """Generate a professional blurb using Gemini."""
    results = search_results.get('results', [])
    context = '\n'.join([f"- {r.get('title', '')}: {r.get('content', '')}" for r in results])[:3000]
    
    if not context.strip():
        context = 'No search results found.'
    
    prompt = f'''Based on these web search results about "{person_name}", write a concise 2-3 sentence professional summary. Focus on their current role, company, and notable achievements. If the search results don't seem relevant to this specific person, just write "Professional on LinkedIn" and nothing else. Be factual, not flowery.

Search results:
{context}

Write only the summary, nothing else:'''

    response = requests.post(
        f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}',
        json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {
                'temperature': 0.3,
                'maxOutputTokens': 150
            }
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    
    try:
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError):
        return 'Professional on LinkedIn.'

def chat_with_network(query, connections, api_key):
    """Chat about the network using Gemini."""
    network_context = '\n'.join([
        f"• {c['firstName']} {c['lastName']}: {c.get('position', '')} at {c.get('company', '')}" + 
        (f" - {c['blurb']}" if c.get('blurb') else '')
        for c in connections
    ])
    
    prompt = f'''You are an assistant helping analyze a professional LinkedIn network. Below is the user's network of {len(connections)} connections.

NETWORK:
{network_context}

USER QUERY: {query}

Analyze the network and provide a helpful, specific response. Reference specific people by name when relevant. Be concise but thorough.'''

    response = requests.post(
        f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}',
        json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {
                'temperature': 0.7,
                'maxOutputTokens': 2000
            }
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    
    try:
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError):
        return 'Unable to generate response.'

# ============ FLASK ROUTES ============
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data():
    data = load_data()
    return jsonify({
        "connections": data.get("connections", []),
        "hasKeys": bool(data.get("api_keys", {}).get("tavily") and data.get("api_keys", {}).get("gemini"))
    })

@app.route('/api/keys', methods=['POST'])
def save_keys():
    data = load_data()
    keys = request.json
    data["api_keys"] = {
        "tavily": keys.get("tavily", ""),
        "gemini": keys.get("gemini", "")
    }
    save_data(data)
    return jsonify({"success": True})

@app.route('/api/upload', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "Must be a CSV file"}), 400
    
    # Save temporarily and parse
    temp_path = Path(__file__).parent / "temp_upload.csv"
    file.save(temp_path)
    
    try:
        connections = parse_linkedin_csv(temp_path)
        if not connections:
            return jsonify({"error": "No connections found in CSV"}), 400
        
        data = load_data()
        data["connections"] = connections
        save_data(data)
        
        return jsonify({"success": True, "count": len(connections)})
    finally:
        temp_path.unlink(missing_ok=True)

@app.route('/api/enrich', methods=['POST'])
def enrich_connection():
    """Enrich a single connection."""
    conn_id = request.json.get("id")
    data = load_data()
    
    api_keys = data.get("api_keys", {})
    if not api_keys.get("tavily") or not api_keys.get("gemini"):
        return jsonify({"error": "API keys not configured"}), 400
    
    conn = next((c for c in data["connections"] if c["id"] == conn_id), None)
    if not conn:
        return jsonify({"error": "Connection not found"}), 404
    
    try:
        name = f"{conn['firstName']} {conn['lastName']}".strip()
        query = ' '.join(filter(None, [name, conn.get('position'), conn.get('company')]))
        
        search_results = search_tavily(query, api_keys["tavily"])
        blurb = generate_blurb(search_results, name, api_keys["gemini"])
        
        conn["blurb"] = blurb
        conn["enrichedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_data(data)
        
        return jsonify({"success": True, "blurb": blurb})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/enrich-batch', methods=['POST'])
def enrich_batch():
    """Enrich a batch of connections (up to 10 at a time to avoid timeouts)."""
    data = load_data()
    api_keys = data.get("api_keys", {})
    
    if not api_keys.get("tavily") or not api_keys.get("gemini"):
        return jsonify({"error": "API keys not configured"}), 400
    
    # Get unenriched connections
    unenriched = [c for c in data["connections"] if not c.get("blurb")][:10]
    
    if not unenriched:
        return jsonify({"success": True, "enriched": 0, "remaining": 0})
    
    enriched_count = 0
    errors = []
    
    for conn in unenriched:
        try:
            name = f"{conn['firstName']} {conn['lastName']}".strip()
            query = ' '.join(filter(None, [name, conn.get('position'), conn.get('company')]))
            
            search_results = search_tavily(query, api_keys["tavily"])
            time.sleep(0.1)  # Small buffer
            blurb = generate_blurb(search_results, name, api_keys["gemini"])
            
            conn["blurb"] = blurb
            conn["enrichedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            enriched_count += 1
            
            # Rate limit: ~4 seconds between to stay under 15 RPM
            time.sleep(4)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    
    save_data(data)
    
    remaining = len([c for c in data["connections"] if not c.get("blurb")])
    return jsonify({
        "success": True,
        "enriched": enriched_count,
        "remaining": remaining,
        "errors": errors
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Chat with the network."""
    query = request.json.get("query", "")
    if not query.strip():
        return jsonify({"error": "No query provided"}), 400
    
    data = load_data()
    api_keys = data.get("api_keys", {})
    
    if not api_keys.get("gemini"):
        return jsonify({"error": "Gemini API key not configured"}), 400
    
    try:
        response = chat_with_network(query, data["connections"], api_keys["gemini"])
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reset', methods=['POST'])
def reset_data():
    """Reset all data."""
    DATA_FILE.unlink(missing_ok=True)
    return jsonify({"success": True})

# ============ HTML TEMPLATE ============
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NetworkIQ</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { font-family: 'IBM Plex Sans', sans-serif; }
    .mono { font-family: 'IBM Plex Mono', monospace; }
    .scrollbar-thin::-webkit-scrollbar { width: 6px; }
    .scrollbar-thin::-webkit-scrollbar-thumb { background: #e5e5e5; border-radius: 3px; }
  </style>
</head>
<body class="bg-neutral-50 min-h-screen">
  <div id="app"></div>
  
  <script>
    // State
    let state = {
      connections: [],
      hasKeys: false,
      view: 'loading',
      activeTab: 'chat',
      searchQuery: '',
      categoryFilter: 'all',
      chatMessages: [],
      isEnriching: false,
      enrichProgress: { current: 0, total: 0 }
    };

    const CATEGORY_COLORS = {
      'Founders': 'bg-violet-100 text-violet-700',
      'Executives': 'bg-amber-100 text-amber-700',
      'Leadership': 'bg-orange-100 text-orange-700',
      'Recruiting': 'bg-emerald-100 text-emerald-700',
      'Investors': 'bg-sky-100 text-sky-700',
      'Engineering': 'bg-blue-100 text-blue-700',
      'Product': 'bg-indigo-100 text-indigo-700',
      'Design': 'bg-pink-100 text-pink-700',
      'Sales': 'bg-lime-100 text-lime-700',
      'Marketing': 'bg-fuchsia-100 text-fuchsia-700',
      'Consulting': 'bg-cyan-100 text-cyan-700',
      'Students': 'bg-teal-100 text-teal-700',
      'Data': 'bg-purple-100 text-purple-700',
      'Finance': 'bg-green-100 text-green-700',
      'Legal': 'bg-slate-100 text-slate-700',
      'Operations': 'bg-stone-100 text-stone-700',
      'Other': 'bg-gray-100 text-gray-600'
    };

    // API calls
    async function api(endpoint, options = {}) {
      const res = await fetch(`/api${endpoint}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      return res.json();
    }

    async function loadData() {
      const data = await api('/data');
      state.connections = data.connections || [];
      state.hasKeys = data.hasKeys;
      state.view = !state.hasKeys ? 'keys' : state.connections.length === 0 ? 'upload' : 'app';
      render();
    }

    async function saveKeys() {
      const tavily = document.getElementById('tavily-key').value;
      const gemini = document.getElementById('gemini-key').value;
      
      if (!tavily || !gemini) {
        alert('Both API keys are required');
        return;
      }
      
      await api('/keys', { method: 'POST', body: JSON.stringify({ tavily, gemini }) });
      state.hasKeys = true;
      state.view = state.connections.length === 0 ? 'upload' : 'app';
      render();
    }

    async function uploadCSV() {
      const input = document.getElementById('csv-input');
      const file = input.files[0];
      if (!file) return;
      
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      const data = await res.json();
      
      if (data.error) {
        alert(data.error);
        return;
      }
      
      await loadData();
    }

    async function enrichAll() {
      if (state.isEnriching) return;
      
      const unenriched = state.connections.filter(c => !c.blurb).length;
      if (unenriched === 0) {
        alert('All connections are already enriched!');
        return;
      }
      
      state.isEnriching = true;
      state.enrichProgress = { current: 0, total: unenriched };
      render();
      
      while (state.isEnriching) {
        const result = await api('/enrich-batch', { method: 'POST', body: '{}' });
        
        if (result.error) {
          alert(result.error);
          state.isEnriching = false;
          break;
        }
        
        state.enrichProgress.current += result.enriched;
        
        if (result.remaining === 0) {
          state.isEnriching = false;
        }
        
        await loadData();
      }
    }

    function stopEnrichment() {
      state.isEnriching = false;
      render();
    }

    async function enrichSingle(id) {
      const result = await api('/enrich', { method: 'POST', body: JSON.stringify({ id }) });
      if (result.error) {
        alert(result.error);
        return;
      }
      await loadData();
    }

    async function sendChat() {
      const input = document.getElementById('chat-input');
      const query = input.value.trim();
      if (!query) return;
      
      state.chatMessages.push({ role: 'user', content: query });
      input.value = '';
      render();
      
      const result = await api('/chat', { method: 'POST', body: JSON.stringify({ query }) });
      
      if (result.error) {
        state.chatMessages.push({ role: 'assistant', content: 'Error: ' + result.error });
      } else {
        state.chatMessages.push({ role: 'assistant', content: result.response });
      }
      render();
      
      // Scroll to bottom
      setTimeout(() => {
        const container = document.getElementById('chat-messages');
        if (container) container.scrollTop = container.scrollHeight;
      }, 100);
    }

    async function resetAll() {
      if (!confirm('This will delete all your data. Are you sure?')) return;
      await api('/reset', { method: 'POST', body: '{}' });
      state = { ...state, connections: [], hasKeys: false, view: 'keys', chatMessages: [] };
      render();
    }

    // Render functions
    function render() {
      const app = document.getElementById('app');
      
      if (state.view === 'loading') {
        app.innerHTML = '<div class="flex items-center justify-center h-screen"><p class="text-neutral-500">Loading...</p></div>';
        return;
      }
      
      if (state.view === 'keys') {
        app.innerHTML = renderKeysView();
        return;
      }
      
      if (state.view === 'upload') {
        app.innerHTML = renderUploadView();
        return;
      }
      
      app.innerHTML = renderAppView();
    }

    function renderKeysView() {
      return `
        <div class="min-h-screen flex items-center justify-center p-6">
          <div class="w-full max-w-md">
            <div class="text-center mb-8">
              <h1 class="text-2xl font-bold text-neutral-900 mb-2">NetworkIQ</h1>
              <p class="text-neutral-500">AI-powered LinkedIn network analysis</p>
            </div>
            <div class="bg-white border border-neutral-200 rounded-xl p-6 space-y-5">
              <div>
                <h2 class="font-semibold text-neutral-900 mb-1">API Keys Required</h2>
                <p class="text-sm text-neutral-500">Both are free. Your keys stay on your machine.</p>
              </div>
              <div>
                <label class="block text-sm font-medium text-neutral-700 mb-1.5">Tavily API Key</label>
                <input id="tavily-key" type="password" placeholder="tvly-..." class="mono w-full px-3 py-2 border border-neutral-200 rounded-lg text-sm">
                <p class="text-xs text-neutral-400 mt-1">Get one at <a href="https://app.tavily.com" target="_blank" class="underline">app.tavily.com</a></p>
              </div>
              <div>
                <label class="block text-sm font-medium text-neutral-700 mb-1.5">Google Gemini API Key</label>
                <input id="gemini-key" type="password" placeholder="AIza..." class="mono w-full px-3 py-2 border border-neutral-200 rounded-lg text-sm">
                <p class="text-xs text-neutral-400 mt-1">Get one at <a href="https://aistudio.google.com/apikey" target="_blank" class="underline">aistudio.google.com</a></p>
              </div>
              <button onclick="saveKeys()" class="w-full bg-neutral-900 text-white py-2 rounded-lg font-medium hover:bg-neutral-800">Continue</button>
            </div>
          </div>
        </div>
      `;
    }

    function renderUploadView() {
      return `
        <div class="min-h-screen flex items-center justify-center p-6">
          <div class="w-full max-w-md">
            <div class="text-center mb-8">
              <h1 class="text-2xl font-bold text-neutral-900 mb-2">NetworkIQ</h1>
              <p class="text-neutral-500">Upload your LinkedIn connections</p>
            </div>
            <div class="bg-white border-2 border-dashed border-neutral-300 rounded-xl p-8 text-center">
              <input id="csv-input" type="file" accept=".csv" onchange="uploadCSV()" class="hidden">
              <div onclick="document.getElementById('csv-input').click()" class="cursor-pointer">
                <div class="w-12 h-12 bg-neutral-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <svg class="w-6 h-6 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                  </svg>
                </div>
                <p class="font-medium text-neutral-700 mb-1">Click to upload Connections.csv</p>
                <p class="text-sm text-neutral-500">From LinkedIn Data Export</p>
              </div>
            </div>
            <button onclick="state.view='keys';render()" class="mt-4 text-sm text-neutral-500 hover:text-neutral-700 mx-auto block">← Back to API keys</button>
          </div>
        </div>
      `;
    }

    function renderAppView() {
      const enrichedCount = state.connections.filter(c => c.blurb).length;
      const categories = {};
      state.connections.forEach(c => { categories[c.category] = (categories[c.category] || 0) + 1; });
      const sortedCategories = Object.entries(categories).sort((a, b) => b[1] - a[1]);
      
      const filtered = state.connections.filter(c => {
        const matchesSearch = !state.searchQuery || 
          `${c.firstName} ${c.lastName} ${c.company} ${c.position}`.toLowerCase().includes(state.searchQuery.toLowerCase());
        const matchesCategory = state.categoryFilter === 'all' || c.category === state.categoryFilter;
        return matchesSearch && matchesCategory;
      });

      return `
        <div class="min-h-screen flex flex-col">
          <!-- Header -->
          <header class="bg-white border-b border-neutral-200 px-6 py-4">
            <div class="max-w-6xl mx-auto flex items-center justify-between">
              <div class="flex items-center gap-6">
                <h1 class="text-lg font-bold text-neutral-900">NetworkIQ</h1>
                <div class="flex items-center gap-1 bg-neutral-100 rounded-lg p-1">
                  <button onclick="state.activeTab='chat';render()" class="px-4 py-1.5 text-sm font-medium rounded-md ${state.activeTab === 'chat' ? 'bg-white text-neutral-900 shadow-sm' : 'text-neutral-500'}">Chat</button>
                  <button onclick="state.activeTab='browse';render()" class="px-4 py-1.5 text-sm font-medium rounded-md ${state.activeTab === 'browse' ? 'bg-white text-neutral-900 shadow-sm' : 'text-neutral-500'}">Browse</button>
                </div>
              </div>
              <div class="flex items-center gap-4">
                <div class="text-sm text-neutral-500">
                  <span class="mono">${state.connections.length}</span> connections · <span class="mono text-emerald-600">${enrichedCount}</span> enriched
                </div>
                <button onclick="resetAll()" class="text-sm text-neutral-400 hover:text-neutral-600">Reset</button>
              </div>
            </div>
          </header>

          <!-- Enrichment Bar -->
          ${enrichedCount < state.connections.length ? `
          <div class="bg-neutral-50 border-b border-neutral-200 px-6 py-3">
            <div class="max-w-6xl mx-auto flex items-center gap-4">
              ${state.isEnriching ? `
                <div class="flex-1">
                  <div class="flex justify-between text-sm mb-1">
                    <span class="text-neutral-600">Enriching connections...</span>
                    <span class="mono text-neutral-500">${state.enrichProgress.current}/${state.enrichProgress.total}</span>
                  </div>
                  <div class="h-2 bg-neutral-200 rounded-full overflow-hidden">
                    <div class="h-full bg-neutral-900 rounded-full" style="width: ${Math.round(state.enrichProgress.current / state.enrichProgress.total * 100)}%"></div>
                  </div>
                </div>
                <button onclick="stopEnrichment()" class="px-4 py-1.5 text-sm font-medium border border-neutral-200 rounded-lg bg-white">Stop</button>
              ` : `
                <p class="text-sm text-neutral-600 flex-1">
                  <span class="mono">${state.connections.length - enrichedCount}</span> connections ready to enrich
                  <span class="text-neutral-400 ml-2">(~${Math.ceil((state.connections.length - enrichedCount) * 4 / 60)} min)</span>
                </p>
                <button onclick="enrichAll()" class="px-4 py-1.5 text-sm font-medium bg-neutral-900 text-white rounded-lg">Enrich All</button>
              `}
            </div>
          </div>
          ` : ''}

          <!-- Main Content -->
          <main class="flex-1 overflow-hidden">
            ${state.activeTab === 'chat' ? renderChatView() : renderBrowseView(filtered, sortedCategories)}
          </main>
        </div>
      `;
    }

    function renderChatView() {
      return `
        <div class="h-full flex flex-col max-w-3xl mx-auto">
          <div id="chat-messages" class="flex-1 overflow-y-auto p-6 space-y-4 scrollbar-thin">
            ${state.chatMessages.length === 0 ? `
              <div class="h-full flex flex-col items-center justify-center text-center py-12">
                <div class="w-16 h-16 bg-neutral-100 rounded-full flex items-center justify-center mb-4">
                  <svg class="w-8 h-8 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                  </svg>
                </div>
                <h2 class="text-lg font-semibold text-neutral-900 mb-2">Chat with your network</h2>
                <p class="text-neutral-500 max-w-sm mb-6">Ask questions like "Who can help me get a job in fintech?" or "List all founders I know."</p>
              </div>
            ` : state.chatMessages.map(m => `
              <div class="flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}">
                <div class="max-w-[80%] px-4 py-3 rounded-2xl ${m.role === 'user' ? 'bg-neutral-900 text-white rounded-br-md' : 'bg-white border border-neutral-200 rounded-bl-md'}">
                  <p class="text-sm whitespace-pre-wrap">${m.content}</p>
                </div>
              </div>
            `).join('')}
          </div>
          <div class="p-4 border-t border-neutral-200 bg-white">
            <div class="flex gap-3">
              <input id="chat-input" onkeydown="if(event.key==='Enter')sendChat()" placeholder="Ask about your network..." class="flex-1 px-4 py-2.5 bg-neutral-50 border border-neutral-200 rounded-xl text-sm">
              <button onclick="sendChat()" class="px-4 py-2 bg-neutral-900 text-white rounded-lg font-medium text-sm">Send</button>
            </div>
          </div>
        </div>
      `;
    }

    function renderBrowseView(filtered, categories) {
      return `
        <div class="h-full flex flex-col">
          <div class="p-4 border-b border-neutral-200 bg-white">
            <div class="max-w-6xl mx-auto flex flex-wrap items-center gap-4">
              <input oninput="state.searchQuery=this.value;render()" placeholder="Search connections..." value="${state.searchQuery}" class="flex-1 min-w-[200px] px-4 py-2 bg-neutral-50 border border-neutral-200 rounded-lg text-sm">
              <select onchange="state.categoryFilter=this.value;render()" class="px-4 py-2 border border-neutral-200 rounded-lg text-sm">
                <option value="all" ${state.categoryFilter === 'all' ? 'selected' : ''}>All Categories</option>
                ${categories.map(([cat, count]) => `<option value="${cat}" ${state.categoryFilter === cat ? 'selected' : ''}>${cat} (${count})</option>`).join('')}
              </select>
            </div>
          </div>
          <div class="flex-1 overflow-y-auto p-4 scrollbar-thin">
            <div class="max-w-6xl mx-auto">
              <p class="text-sm text-neutral-500 mb-4">Showing <span class="mono font-medium">${filtered.length}</span> of <span class="mono">${state.connections.length}</span></p>
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                ${filtered.map(c => `
                  <div class="p-4 bg-white border border-neutral-200 rounded-lg hover:border-neutral-300">
                    <div class="flex items-start justify-between gap-3">
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <h3 class="font-semibold text-neutral-900 truncate">${c.firstName} ${c.lastName}</h3>
                          <span class="px-2 py-0.5 text-xs font-medium rounded ${CATEGORY_COLORS[c.category] || 'bg-gray-100 text-gray-600'}">${c.category}</span>
                        </div>
                        <p class="text-sm text-neutral-600 truncate">${[c.position, c.company].filter(Boolean).join(' at ') || 'No title'}</p>
                        ${c.blurb ? `<p class="mt-2 text-sm text-neutral-500 line-clamp-2">${c.blurb}</p>` : ''}
                      </div>
                      ${!c.blurb ? `<button onclick="enrichSingle('${c.id}')" class="px-3 py-1.5 text-sm border border-neutral-200 rounded-lg hover:bg-neutral-50">Enrich</button>` : `<span class="text-emerald-600 text-xs font-medium">✓ Enriched</span>`}
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        </div>
      `;
    }

    // Initialize
    loadData();
  </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("\\n" + "="*50)
    print("  NetworkIQ - LinkedIn Network Analyzer")
    print("="*50)
    print("\\nStarting server at: http://localhost:5000")
    print("Press Ctrl+C to stop\\n")
    app.run(debug=False, port=5000)
