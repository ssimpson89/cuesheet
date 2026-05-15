// AI Assistant Chat Interface Logic

// Global state
let ws = null;
let pendingNonce = null;

function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Initialize WebSocket connection for context updates
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'state_update') {
            updateContext(msg.state);
        } else if (msg.type === 'ai_operation_complete') {
            // Refresh context after AI operation
            fetchContext();
        }
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('WebSocket closed, reconnecting...');
        setTimeout(initWebSocket, 1000);
    };
}

// Update context display
function updateContext(state) {
    document.getElementById('displayServiceName').textContent = state.script_name || 'CueSheet';
    document.getElementById('ctxShowName').textContent = state.script_name || 'CueSheet';
    
    if (state.sequence_number) {
        const cueText = state.line_text ? state.line_text.substring(0, 30) + '...' : '';
        document.getElementById('ctxCurrentCue').textContent = `#${state.sequence_number}: ${cueText}`;
    } else {
        document.getElementById('ctxCurrentCue').textContent = 'No cue selected';
    }
}

// Fetch current context via API
async function fetchContext() {
    try {
        const response = await fetch('/api/state');
        const state = await response.json();
        updateContext(state);
        
        // Also update total cues count
        const cuesResponse = await fetch('/api/cues/all');
        const cues = await cuesResponse.json();
        document.getElementById('ctxTotalCues').textContent = cues.length || 0;
    } catch (error) {
        console.error('Failed to fetch context:', error);
    }
}

// Fetch usage stats
async function fetchUsageStats() {
    try {
        const response = await fetch('/api/ai/usage');
        const data = await response.json();
        
        if (data.error) {
            document.getElementById('usageStats').classList.add('hidden');
            return;
        }
        
        document.getElementById('usageCount').textContent = data.count_today;
        
        if (data.limit > 0) {
            document.getElementById('usageLimit').textContent = `Limit: ${data.limit}/day`;
            
            // Warn if approaching limit
            if (data.count_today >= data.limit * 0.9) {
                document.getElementById('usageDisplay').classList.add('text-red-500');
            }
        } else {
            document.getElementById('usageLimit').textContent = 'No limit';
        }
    } catch (error) {
        console.error('Failed to fetch usage stats:', error);
    }
}

// Send message to AI
async function sendMessage() {
    const input = document.getElementById('messageInput');
    const userMessage = input.value.trim();
    
    if (!userMessage) return;
    
    // Clear input
    input.value = '';
    
    // Add user message to chat
    appendMessage('user', userMessage);
    
    // Show typing indicator
    const typingId = showTyping();
    
    try {
        // Call AI API
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: userMessage,
                include_context: true
            })
        });
        
        const data = await response.json();
        
        // Remove typing indicator
        removeTyping(typingId);
        
        if (data.error) {
            appendMessage('assistant', `❌ Error: ${data.error}`, 'error');
            return;
        }
        
        if (data.preview) {
            // Server-issued nonce binds confirm to the previewed operations.
            pendingNonce = data.nonce;
            showPreview(data.confirmation_message);
        } else {
            // Direct execution - show result
            appendMessage('assistant', data.response);
            
            // Update usage stats
            if (data.usage) {
                document.getElementById('usageCount').textContent = data.usage.count_today;
            }
        }
        
    } catch (error) {
        removeTyping(typingId);
        appendMessage('assistant', `❌ Network error: ${error.message}`, 'error');
    }
}

// Append message to chat.
// Pass `type === 'preview'` to render trusted HTML (only used internally by
// showPreview). All other roles receive escaped plain text.
function appendMessage(role, content, type = 'normal') {
    const messagesDiv = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex gap-3';

    let iconHtml, bgColor, textColor;

    if (role === 'user') {
        iconHtml = '<i data-lucide="user" class="w-4 h-4"></i>';
        bgColor = 'bg-blue-100';
        textColor = 'text-blue-900';
    } else {
        iconHtml = '<i data-lucide="bot" class="w-4 h-4"></i>';
        bgColor = type === 'error' ? 'bg-red-50' : 'bg-white';
        textColor = type === 'error' ? 'text-red-900' : 'text-gray-700';
    }

    const body = type === 'preview' ? content : escapeHtml(content);

    messageDiv.innerHTML = `
        <div class="w-8 h-8 rounded-full ${role === 'user' ? 'bg-blue-500' : 'bg-purple-500'} flex items-center justify-center text-white flex-shrink-0">
            ${iconHtml}
        </div>
        <div class="flex-1">
            <div class="${bgColor} rounded-lg p-4 shadow ${type === 'preview' ? 'border-l-4 border-yellow-400' : ''}">
                <div class="${textColor} whitespace-pre-wrap">${body}</div>
            </div>
        </div>
    `;

    messagesDiv.appendChild(messageDiv);

    lucide.createIcons();
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Show typing indicator
function showTyping() {
    const messagesDiv = document.getElementById('chatMessages');
    const typingDiv = document.createElement('div');
    const typingId = `typing-${Date.now()}`;
    typingDiv.id = typingId;
    typingDiv.className = 'flex gap-3';
    typingDiv.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-purple-500 flex items-center justify-center text-white flex-shrink-0">
            <i data-lucide="bot" class="w-4 h-4"></i>
        </div>
        <div class="flex-1">
            <div class="bg-white rounded-lg p-4 shadow">
                <div class="flex gap-1">
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
                    <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                </div>
            </div>
        </div>
    `;
    
    messagesDiv.appendChild(typingDiv);
    lucide.createIcons();
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    return typingId;
}

// Remove typing indicator
function removeTyping(typingId) {
    const typingDiv = document.getElementById(typingId);
    if (typingDiv) {
        typingDiv.remove();
    }
}

// Show preview confirmation. The message string is escaped before being
// interpolated into the preview HTML.
function showPreview(message) {
    const content = `
        <div class="space-y-3">
            <p><strong>Confirmation Required</strong></p>
            <p>${escapeHtml(message)}</p>
            <div class="flex gap-2 mt-3">
                <button onclick="confirmOperation()" class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-1">
                    <i data-lucide="check" class="w-4 h-4"></i>
                    Confirm
                </button>
                <button onclick="cancelOperation()" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors flex items-center gap-1">
                    <i data-lucide="x" class="w-4 h-4"></i>
                    Cancel
                </button>
            </div>
        </div>
    `;

    appendMessage('assistant', content, 'preview');
}

// Confirm pending operation using the server-issued nonce.
async function confirmOperation() {
    if (!pendingNonce) return;

    const typingId = showTyping();
    const nonce = pendingNonce;
    pendingNonce = null;

    try {
        const response = await fetch('/api/ai/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ nonce: nonce })
        });

        const data = await response.json();
        removeTyping(typingId);

        if (!response.ok || data.error || data.detail) {
            const msg = data.error || data.detail || `HTTP ${response.status}`;
            appendMessage('assistant', `Error: ${msg}`, 'error');
        } else {
            appendMessage('assistant', data.response);
            if (data.usage) {
                document.getElementById('usageCount').textContent = data.usage.count_today;
            }
        }
    } catch (error) {
        removeTyping(typingId);
        appendMessage('assistant', `Network error: ${error.message}`, 'error');
    }
}

// Cancel pending operation
function cancelOperation() {
    appendMessage('assistant', 'Operation cancelled.');
    pendingNonce = null;
}

// Fill example command
function fillExample(text) {
    document.getElementById('messageInput').value = text;
    document.getElementById('messageInput').focus();
}

// Show bulk import modal
function showBulkImport() {
    document.getElementById('bulkImportModal').classList.remove('hidden');
    document.getElementById('bulkImportText').focus();
}

// Close bulk import modal
function closeBulkImport() {
    document.getElementById('bulkImportModal').classList.add('hidden');
    document.getElementById('bulkImportText').value = '';
}

// Process bulk import
async function processBulkImport() {
    const scriptText = document.getElementById('bulkImportText').value.trim();
    const autoSuggest = document.getElementById('autoSuggestCameras').checked;
    
    if (!scriptText) {
        alert('Please paste script text');
        return;
    }
    
    closeBulkImport();
    
    appendMessage('user', `📄 Import script (${scriptText.split('\n').length} lines)`);
    const typingId = showTyping();
    
    try {
        const response = await fetch('/api/ai/bulk-import', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                script_text: scriptText,
                auto_suggest_cameras: autoSuggest
            })
        });
        
        const data = await response.json();
        removeTyping(typingId);
        
        if (data.error) {
            appendMessage('assistant', `❌ Error: ${data.error}`, 'error');
        } else {
            appendMessage('assistant', data.response);
            
            // Update usage stats
            if (data.usage) {
                document.getElementById('usageCount').textContent = data.usage.count_today;
            }
        }
        
    } catch (error) {
        removeTyping(typingId);
        appendMessage('assistant', `❌ Network error: ${error.message}`, 'error');
    }
}

// Form submit handler
document.getElementById('chatForm').addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage();
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    fetchContext();
    fetchUsageStats();
});
