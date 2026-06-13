// Global Variables & Setup
let ws = null;
let currentMode = 'ask'; // 'ask', 'plan', or 'agent'
let webToken = '';
let activeAgentMessageElement = null;
let activeAgentMessageText = '';

// Initialize application on load
document.addEventListener('DOMContentLoaded', () => {
  setupAuthentication();
  setupSidebarNavigation();
  setupModeSelector();
  setupConsoleInput();
  setupRAGControls();
  setupWorkspaceExplorer();
  setupMemoryViewer();
  connectWebSocket();
  fetchInitialStatus();
});

// Auth Setup: retrieve token from URL parameters or local storage
function setupAuthentication() {
  const urlParams = new URLSearchParams(window.location.search);
  const tokenFromUrl = urlParams.get('token');
  
  if (tokenFromUrl) {
    webToken = tokenFromUrl;
    localStorage.setItem('nakama_web_token', tokenFromUrl);
    // Clean up URL query parameters
    const newUrl = window.location.protocol + '//' + window.location.host + window.location.pathname;
    window.history.replaceState({ path: newUrl }, '', newUrl);
  } else {
    webToken = localStorage.getItem('nakama_web_token') || '';
  }
}

// Fetch general configuration status
async function fetchInitialStatus() {
  try {
    const res = await apiRequest('/api/status');
    document.getElementById('workspace-root-path').textContent = res.workspace_root;
    document.getElementById('rag-db-path').textContent = res.rag_db_path || 'Disabled';
    
    const ragBadge = document.getElementById('rag-status-badge');
    if (res.rag_enabled) {
      ragBadge.textContent = 'Enabled';
      ragBadge.className = 'badge success';
    } else {
      ragBadge.textContent = 'Disabled';
      ragBadge.className = 'badge';
    }

    const mcpCount = document.getElementById('mcp-servers-count');
    const mcpList = document.getElementById('mcp-servers-list');
    mcpList.innerHTML = '';
    
    if (res.mcp_servers && res.mcp_servers.length > 0) {
      mcpCount.textContent = `${res.mcp_servers.length} connected`;
      res.mcp_servers.forEach(server => {
        const item = document.createElement('div');
        item.className = 'mcp-server-item';
        item.innerHTML = `
          <span class="mcp-server-name">${server.name}</span>
          <span class="badge ${server.connected ? 'success' : ''}">${server.connected ? 'Connected' : 'Offline'}</span>
        `;
        mcpList.appendChild(item);
      });
    } else {
      mcpCount.textContent = 'None';
    }
  } catch (err) {
    showToast('❌ Failed to fetch config status', 'danger');
  }
}

// REST API Request Wrapper with Token Headers
async function apiRequest(url, options = {}) {
  const headers = options.headers || {};
  headers['X-Web-Token'] = webToken;
  
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    showToast('🔒 Unauthorized. Please provide a valid session token.', 'danger');
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'API Request failed');
  }
  return await res.json();
}

// WebSocket Connection Setup
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/ws/agent?token=${webToken}`;
  
  ws = new WebSocket(wsUrl);
  
  ws.onopen = () => {
    loggerLog('WebSocket connected.', 'system');
  };
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleWebSocketMessage(data);
  };
  
  ws.onerror = (err) => {
    loggerLog('WebSocket connection error.', 'warning');
    showToast('⚠️ WebSocket connection error', 'warning');
  };
  
  ws.onclose = () => {
    loggerLog('WebSocket connection closed. Reconnecting...', 'warning');
    setTimeout(connectWebSocket, 3000);
  };
}

// Dispatch actions based on websocket event type
function handleWebSocketMessage(data) {
  switch (data.type) {
    case 'token':
      // Streaming token
      if (!activeAgentMessageElement) {
        activeAgentMessageElement = createChatBubble('assistant', '🤖');
      }
      activeAgentMessageText += data.content;
      activeAgentMessageElement.innerHTML = formatMarkdown(activeAgentMessageText);
      scrollChatToBottom();
      break;
      
    case 'plan':
      // Plan Mode structured response
      renderPlanCard(data);
      scrollChatToBottom();
      break;
      
    case 'agent_node':
      // Workflow status updates
      updateAgentWorkflowState(data.node, data.status);
      break;
      
    case 'agent_log':
      // Logger sidebar updates
      loggerLog(data.log);
      break;
      
    case 'approval_required':
      // Diff checkpoints approval popup
      showApprovalModal(data);
      break;
      
    case 'done':
      // Complete notification
      if (activeAgentMessageElement) {
        activeAgentMessageElement.parentElement.classList.remove('loading');
      }
      activeAgentMessageElement = null;
      activeAgentMessageText = '';
      setTimelineLoadingState(false);
      showToast('✓ Task completed!', 'success');
      break;
      
    case 'error':
      // System error
      if (activeAgentMessageElement) {
        activeAgentMessageElement.innerHTML = `<span style="color:var(--danger)">Error: ${data.message}</span>`;
      } else {
        createChatBubble('assistant', '🤖', `❌ Error occurred: ${data.message}`);
      }
      activeAgentMessageElement = null;
      activeAgentMessageText = '';
      setTimelineLoadingState(false);
      showToast('❌ Error: ' + data.message, 'danger');
      loggerLog(`ERROR: ${data.message}`, 'warning');
      break;
  }
}

// Send Instruction trigger
function sendUserPrompt() {
  const inputEl = document.getElementById('prompt-input');
  const text = inputEl.value.trim();
  if (!text) return;
  
  // Create user bubble
  createChatBubble('user', '👤', text);
  inputEl.value = '';
  
  // Show active loaders for Agent mode
  if (currentMode === 'agent') {
    document.getElementById('agent-workflow-bar').style.display = 'flex';
    document.getElementById('logs-sidebar-wrapper').style.display = 'flex';
    document.querySelector('.console-grid').classList.add('with-sidebar');
    setTimelineLoadingState(true);
    loggerLog(`Triggering agent workflow: "${text}"`, 'system');
  } else {
    document.getElementById('agent-workflow-bar').style.display = 'none';
    document.getElementById('logs-sidebar-wrapper').style.display = 'none';
    document.querySelector('.console-grid').classList.remove('with-sidebar');
  }

  // Send request via WebSocket
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: currentMode,
      text: text
    }));
  } else {
    showToast('🔌 Connection offline. Trying to reconnect...', 'warning');
  }
  
  activeAgentMessageElement = null;
  activeAgentMessageText = '';
  scrollChatToBottom();
}

// Tabs Navigation
function setupSidebarNavigation() {
  const navItems = document.querySelectorAll('.nav-item');
  const panels = document.querySelectorAll('.tab-panel');
  
  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const tabId = item.getAttribute('data-tab');
      
      navItems.forEach(n => n.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      
      item.classList.add('active');
      document.getElementById(tabId).classList.add('active');
      
      // Load specific data when switching to views
      if (tabId === 'workspace') {
        refreshFilesList();
      } else if (tabId === 'memory') {
        refreshMemoryList();
      }
    });
  });
}

// Mode pill controls
function setupModeSelector() {
  const pills = document.querySelectorAll('.mode-pill');
  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentMode = pill.getAttribute('data-mode');
    });
  });
}

// Textarea input binds
function setupConsoleInput() {
  const inputEl = document.getElementById('prompt-input');
  const sendBtn = document.getElementById('send-btn');
  
  sendBtn.addEventListener('click', sendUserPrompt);
  
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendUserPrompt();
    }
  });

  document.getElementById('clear-logs-btn').addEventListener('click', () => {
    document.getElementById('agent-logs-container').innerHTML = '';
  });
}

// File Explorer setup
async function refreshFilesList() {
  const treeContainer = document.getElementById('files-tree-container');
  treeContainer.innerHTML = '<div class="loading-spinner">Scanning files...</div>';
  
  try {
    const files = await apiRequest('/api/workspace/files');
    treeContainer.innerHTML = '';
    
    if (files.length === 0) {
      treeContainer.innerHTML = '<div class="info-text">Workspace is empty.</div>';
      return;
    }
    
    files.forEach(file => {
      const fileEl = document.createElement('div');
      fileEl.className = 'file-item';
      fileEl.innerHTML = `
        <span class="file-icon">📄</span>
        <span class="file-name">${file.path}</span>
      `;
      fileEl.addEventListener('click', () => {
        // Toggle selected state
        document.querySelectorAll('.file-item').forEach(f => f.classList.remove('selected'));
        fileEl.classList.add('selected');
        viewFileContent(file.path);
      });
      treeContainer.appendChild(fileEl);
    });
  } catch (err) {
    treeContainer.innerHTML = '<div class="error-text">Failed to load workspace files.</div>';
  }
}

async function viewFileContent(filePath) {
  const titleEl = document.getElementById('active-file-title');
  const sizeBadge = document.getElementById('file-size-badge');
  const codeEl = document.getElementById('code-content');
  
  titleEl.textContent = filePath;
  codeEl.textContent = 'Loading file contents...';
  sizeBadge.style.display = 'none';

  try {
    const res = await apiRequest(`/api/workspace/file?path=${encodeURIComponent(filePath)}`);
    codeEl.textContent = res.content;
    sizeBadge.textContent = `${new Blob([res.content]).size} bytes`;
    sizeBadge.style.display = 'inline-block';
  } catch (err) {
    codeEl.textContent = `Error reading file: ${err.message}`;
  }
}

function setupWorkspaceExplorer() {
  document.getElementById('refresh-files-btn').addEventListener('click', refreshFilesList);
}

// Memory database viewer logic
let memoryTab = 'conversations';

function setupMemoryViewer() {
  const tabs = document.querySelectorAll('.mem-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      memoryTab = tab.getAttribute('data-mem');
      refreshMemoryList();
    });
  });
}

async function refreshMemoryList() {
  const container = document.getElementById('memory-list-container');
  container.innerHTML = '<div class="loading-spinner">Loading database items...</div>';
  
  try {
    if (memoryTab === 'conversations') {
      const convs = await apiRequest('/api/memory/conversations');
      container.innerHTML = '';
      
      if (convs.length === 0) {
        container.innerHTML = '<div class="info-text">No conversation logs found.</div>';
        return;
      }
      
      convs.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'memory-item';
        item.innerHTML = `
          <div class="memory-item-title">${conv.title}</div>
          <div class="memory-item-meta">
            <span>Mode: ${conv.mode}</span>
            <span>${formatTimestamp(conv.created_at)}</span>
          </div>
        `;
        item.addEventListener('click', () => {
          document.querySelectorAll('.memory-item').forEach(m => m.classList.remove('selected'));
          item.classList.add('selected');
          viewConversationDetails(conv);
        });
        container.appendChild(item);
      });
    } else {
      const tasks = await apiRequest('/api/memory/tasks');
      container.innerHTML = '';
      
      if (tasks.length === 0) {
        container.innerHTML = '<div class="info-text">No task execution logs found.</div>';
        return;
      }
      
      tasks.forEach(task => {
        const item = document.createElement('div');
        item.className = 'memory-item';
        item.innerHTML = `
          <div class="memory-item-title">${task.description}</div>
          <div class="memory-item-meta">
            <span class="badge ${task.status === 'done' ? 'success' : ''}">${task.status.toUpperCase()}</span>
            <span>ID: ${task.id.slice(0, 8)}</span>
          </div>
        `;
        item.addEventListener('click', () => {
          document.querySelectorAll('.memory-item').forEach(m => m.classList.remove('selected'));
          item.classList.add('selected');
          viewTaskDetails(task);
        });
        container.appendChild(item);
      });
    }
  } catch (err) {
    container.innerHTML = '<div class="error-text">Failed to fetch memory records.</div>';
  }
}

async function viewConversationDetails(conv) {
  const titleEl = document.getElementById('memory-detail-title');
  const contentEl = document.getElementById('memory-detail-content');
  
  titleEl.innerHTML = `
    <span>${conv.title}</span>
    <button class="action-btn danger" style="padding: 6px 12px; font-size: 11px; margin-left: 12px;" onclick="deleteConversationRecord('${conv.id}')">Delete</button>
  `;
  contentEl.innerHTML = '<div class="loading-spinner">Loading messages...</div>';

  try {
    const messages = await apiRequest(`/api/memory/conversations/${conv.id}/messages`);
    contentEl.innerHTML = '';
    
    messages.forEach(msg => {
      const bubble = document.createElement('div');
      bubble.className = `message ${msg.role}`;
      bubble.innerHTML = `
        <div class="msg-avatar">${msg.role === 'user' ? '👤' : '🤖'}</div>
        <div class="msg-bubble">${formatMarkdown(msg.content)}</div>
      `;
      contentEl.appendChild(bubble);
    });
  } catch (err) {
    contentEl.innerHTML = `<div class="error-text">Failed to load conversation details: ${err.message}</div>`;
  }
}

window.deleteConversationRecord = async function(convId) {
  if (!confirm('Are you sure you want to delete this conversation?')) return;
  try {
    await apiRequest(`/api/memory/conversations/${convId}`, { method: 'DELETE' });
    showToast('Conversation deleted', 'success');
    document.getElementById('memory-detail-title').textContent = 'Select an item';
    document.getElementById('memory-detail-content').textContent = 'Select a past conversation or task to review the history.';
    refreshMemoryList();
  } catch (err) {
    showToast('Failed to delete conversation: ' + err.message, 'danger');
  }
};

function viewTaskDetails(task) {
  const titleEl = document.getElementById('memory-detail-title');
  const contentEl = document.getElementById('memory-detail-content');
  
  titleEl.textContent = `Task: ${task.id.slice(0, 8)}`;
  contentEl.innerHTML = `
    <div class="info-card" style="padding: 20px; background: rgba(0,0,0,0.2); border-radius: 10px; border: 1px solid var(--border-color);">
      <h3 style="margin-bottom: 12px; font-weight: 700;">Task Summary</h3>
      <p style="margin-bottom: 10px;"><strong>Goal Description:</strong></p>
      <blockquote style="padding: 10px; border-left: 4px solid var(--primary); background: rgba(255,255,255,0.02); margin-bottom: 20px;">
        ${task.description}
      </blockquote>
      <div class="info-row" style="margin-bottom: 8px;">
        <span class="info-lbl">Status:</span>
        <span class="badge ${task.status === 'done' ? 'success' : ''}">${task.status.toUpperCase()}</span>
      </div>
      <div class="info-row">
        <span class="info-lbl">Finished At:</span>
        <span>${task.finished_at ? formatTimestamp(task.finished_at) : 'N/A'}</span>
      </div>
    </div>
  `;
}

// RAG Index API Controls
function setupRAGControls() {
  const triggerBtn = (btnId, url, successMsg) => {
    document.getElementById(btnId).addEventListener('click', async () => {
      if (!confirm(`Are you sure you want to trigger this database operation?`)) return;
      showToast('⏳ Processing RAG index action...', 'warning');
      try {
        const res = await apiRequest(url, { method: 'POST' });
        showToast(`✓ ${res.message || successMsg}`, 'success');
        fetchInitialStatus();
      } catch (err) {
        showToast(`❌ Error: ${err.message}`, 'danger');
      }
    });
  };

  triggerBtn('rag-build-btn', '/api/rag/build', 'RAG index successfully built.');
  triggerBtn('rag-refresh-btn', '/api/rag/refresh', 'RAG index successfully refreshed.');
  triggerBtn('rag-clear-btn', '/api/rag/clear', 'RAG database cleared.');
}

// Diff Approvals modal trigger
function showApprovalModal(proposal) {
  const dialog = document.getElementById('approval-dialog');
  document.getElementById('modal-file-path').textContent = proposal.file_path;
  document.getElementById('modal-proposal-badge').textContent = proposal.change_type.toUpperCase();
  document.getElementById('modal-diff-content').textContent = proposal.diff;
  
  const approveBtn = document.getElementById('modal-approve-btn');
  const rejectBtn = document.getElementById('modal-reject-btn');
  
  const cleanHandlers = () => {
    approveBtn.replaceWith(approveBtn.cloneNode(true));
    rejectBtn.replaceWith(rejectBtn.cloneNode(true));
  };
  
  cleanHandlers();
  
  // Fetch fresh buttons
  const newApprove = document.getElementById('modal-approve-btn');
  const newReject = document.getElementById('modal-reject-btn');
  
  newApprove.addEventListener('click', async () => {
    try {
      await apiRequest(`/api/approvals/${proposal.id}/approve`, { method: 'POST' });
      dialog.close();
      showToast('✓ Change approved and applied.', 'success');
      loggerLog(`Approved file change proposal: ${proposal.file_path}`, 'success');
    } catch (err) {
      showToast('Error approving proposal: ' + err.message, 'danger');
    }
  });
  
  newReject.addEventListener('click', async () => {
    try {
      await apiRequest(`/api/approvals/${proposal.id}/reject`, { method: 'POST' });
      dialog.close();
      showToast('✗ Change rejected by user.', 'danger');
      loggerLog(`Rejected file change proposal: ${proposal.file_path}`, 'warning');
    } catch (err) {
      showToast('Error rejecting proposal: ' + err.message, 'danger');
    }
  });
  
  dialog.showModal();
}

// Helper: update Agent visual timeline classes
function updateAgentWorkflowState(node, status) {
  const stepEl = document.getElementById(`step-${node}`);
  if (!stepEl) return;
  
  if (status === 'running') {
    stepEl.classList.remove('completed');
    stepEl.classList.add('running');
  } else if (status === 'completed') {
    stepEl.classList.remove('running');
    stepEl.classList.add('completed');
  }
}

// Reset Timeline statuses
function setTimelineLoadingState(isLoading) {
  const steps = ['planning', 'coding', 'executing', 'reviewing'];
  steps.forEach(step => {
    const el = document.getElementById(`step-${step}`);
    if (el) {
      el.classList.remove('running', 'completed');
    }
  });
}

// Append logs to Sidebar Logger Panel
function loggerLog(message, type = 'normal') {
  const container = document.getElementById('agent-logs-container');
  const el = document.createElement('div');
  el.className = `log-entry ${type}`;
  
  const now = new Date();
  const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
  
  el.textContent = `[${timeStr}] ${message}`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

// Dynamic markdown plan generator view
function renderPlanCard(data) {
  const bubble = document.createElement('div');
  bubble.className = 'message assistant';
  
  let html = `
    <div class="msg-avatar">🤖</div>
    <div class="msg-bubble" style="border-color: var(--warning); background-color: rgba(245, 158, 11, 0.03);">
      <h3 style="color:var(--warning); font-weight:800; font-size:18px; margin-bottom:12px;">📋 Implementation Plan</h3>
      <p style="margin-bottom: 14px;"><strong>Goal Summary:</strong> ${data.goal_summary || 'N/A'}</p>
  `;
  
  if (data.targets && data.targets.length > 0) {
    html += `
      <h4 style="font-weight:700; margin-bottom:6px;">Target Files/Modules</h4>
      <ul style="margin-bottom: 14px;">${data.targets.map(t => `<li><code>${t}</code></li>`).join('')}</ul>
    `;
  }
  
  if (data.assumptions && data.assumptions.length > 0) {
    html += `
      <h4 style="font-weight:700; margin-bottom:6px;">Assumptions</h4>
      <ul style="margin-bottom: 14px;">${data.assumptions.map(a => `<li>${a}</li>`).join('')}</ul>
    `;
  }
  
  if (data.ordered_steps && data.ordered_steps.length > 0) {
    html += `
      <h4 style="font-weight:700; margin-bottom:6px; color:var(--success);">Execution Steps</h4>
      <ol style="margin-bottom: 14px;">${data.ordered_steps.map(s => `<li>${s}</li>`).join('')}</ol>
    `;
  }
  
  if (data.risks && data.risks.length > 0) {
    html += `
      <h4 style="font-weight:700; margin-bottom:6px; color:var(--danger);">Risks & Hazards</h4>
      <ul style="margin-bottom: 14px;">${data.risks.map(r => `<li style="color:var(--danger)">⚠️ ${r}</li>`).join('')}</ul>
    `;
  }
  
  if (data.validation_checklist && data.validation_checklist.length > 0) {
    html += `
      <h4 style="font-weight:700; margin-bottom:6px; color:var(--primary-light);">Validation Checklist</h4>
      <ul style="margin-bottom: 14px;">${data.validation_checklist.map(v => `<li>☐ ${v}</li>`).join('')}</ul>
    `;
  }
  
  html += '</div>';
  bubble.innerHTML = html;
  document.getElementById('chat-messages-container').appendChild(bubble);
}

// Helper: HTML-safe chat bubbles
function createChatBubble(role, avatar, content = '') {
  const container = document.getElementById('chat-messages-container');
  const bubble = document.createElement('div');
  bubble.className = `message ${role}`;
  if (currentMode === 'agent' && role === 'assistant' && content === '') {
    bubble.classList.add('loading');
  }
  
  bubble.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-bubble">${formatMarkdown(content)}</div>
  `;
  container.appendChild(bubble);
  scrollChatToBottom();
  
  return bubble.querySelector('.msg-bubble');
}

function scrollChatToBottom() {
  const container = document.getElementById('chat-messages-container');
  container.scrollTop = container.scrollHeight;
}

// Simple MarkDown renderer fallback
function formatMarkdown(text) {
  if (!text) return '<p></p>';
  
  // Escape HTML tags to prevent XSS
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
    
  // Format code blocks
  html = html.replace(/```([\s\S]*?)```/g, (match, p1) => {
    return `<pre><code>${p1.trim()}</code></pre>`;
  });
  
  // Inline code snippets
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  
  // Bold strings
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  
  // Bullet items
  html = html.replace(/^\s*-\s+(.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  
  // Paragraphs splitting
  html = html.split('\n\n').map(p => {
    if (p.startsWith('<pre>') || p.startsWith('<ul>')) return p;
    return `<p>${p.replace(/\n/g, '<br>')}</p>`;
  }).join('');
  
  return html;
}

// Show custom toast warnings/alerts
function showToast(message, type = 'normal') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${message}</span>
  `;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Format Unix Timestamp
function formatTimestamp(timestampStr) {
  const date = new Date(timestampStr);
  return date.toLocaleString();
}
