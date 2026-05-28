import { useState, useEffect, useRef, useCallback } from 'react';
import Navbar from '../components/Navbar';
import './Chat.css';

const CHAT_STORAGE_KEY = 'kashe_chat_history';
const PENDING_LOG_CHALLENGE_KEY = 'kashe_pending_log_challenge';

const GREETING_TIMEOUT_MS = 5000;
const CHAT_REQUEST_TIMEOUT_MS = 85000;

const DEFAULT_WELCOME = {
  id: 0,
  text: "Hi! I'm Kai, your Kashé fitness coach. Ask me to plan your week, check your pace, log a class, or redeem rewards!",
  sender: 'ai',
};

const KASHE_HELP_FALLBACK_REPLY =
  "I can help you plan your week, check if you are on pace, log classes, enroll in challenges, or redeem rewards. What would you like?";

function readStoredChat() {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const valid = parsed.filter(
      (m) =>
        m &&
        typeof m === 'object' &&
        typeof m.text === 'string' &&
        (m.sender === 'user' || m.sender === 'ai') &&
        !m.isThinking &&
        !m.isStreaming
    );
    return valid.length > 0 ? valid : null;
  } catch {
    return null;
  }
}

function getPendingLogChallenge() {
  try {
    return sessionStorage.getItem(PENDING_LOG_CHALLENGE_KEY) || null;
  } catch {
    return null;
  }
}

function setPendingLogChallenge(title) {
  try {
    if (title && String(title).trim()) {
      sessionStorage.setItem(PENDING_LOG_CHALLENGE_KEY, String(title).trim());
    } else {
      sessionStorage.removeItem(PENDING_LOG_CHALLENGE_KEY);
    }
  } catch {
    // ignore
  }
}

async function fetchPersonalizedGreeting() {
  const token = localStorage.getItem('token');
  const controller = new AbortController();
  const to = setTimeout(() => controller.abort(), GREETING_TIMEOUT_MS);
  try {
    const response = await fetch('http://127.0.0.1:5000/api/chat/greeting', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok || !data.greeting) {
      throw new Error(data.error || 'greeting failed');
    }
    return data.greeting;
  } finally {
    clearTimeout(to);
  }
}

function isAffirmativeForPending(text) {
  const t = text.trim().toLowerCase();
  if (!t || t.length > 80) return false;
  return /^(yes+|y+|yep+|yeah+|sure+|ok+|okay+|please\b|do it|absolutely|sounds?\s+good|go\s+ahead|\bfine\b|let'?s\s+do\s+it)([\s!.?,]|$)/i.test(
    t
  );
}

/**
 * Read SSE from POST /api/chat/stream; invoke onChunk for each text piece.
 */
async function consumeChatStream({ body, token, signal, onChunk, onMeta }) {
  const response = await fetch('http://127.0.0.1:5000/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let errMsg = `Something went wrong (${response.status}). ${KASHE_HELP_FALLBACK_REPLY}`;
    try {
      const errData = await response.json();
      if (errData.error) errMsg = errData.error;
    } catch {
      // not JSON
    }
    throw new Error(errMsg);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Streaming is not supported in this browser.');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';

    for (const part of parts) {
      const line = part
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l.startsWith('data:'));
      if (!line) continue;

      const payload = line.replace(/^data:\s*/, '');
      if (payload === '[DONE]') {
        return;
      }

      let parsed;
      try {
        parsed = JSON.parse(payload);
      } catch {
        continue;
      }

      if (parsed.error) {
        throw new Error(parsed.error);
      }
      if (parsed.meta && onMeta) {
        onMeta(parsed.meta);
      }
      if (typeof parsed.chunk === 'string' && parsed.chunk.length > 0) {
        onChunk(parsed.chunk);
      }
    }
  }
}

function Chat({ setIsAuthenticated }) {
  const [messages, setMessages] = useState(() => readStoredChat() ?? null);
  const [greetingLoading, setGreetingLoading] = useState(() => !readStoredChat());
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [inputHint, setInputHint] = useState('');
  const messagesEndRef = useRef(null);
  const greetingFetchGenRef = useRef(0);

  const loadFreshGreeting = useCallback(async () => {
    const gen = ++greetingFetchGenRef.current;
    setGreetingLoading(true);
    setMessages(null);
    try {
      const text = await fetchPersonalizedGreeting();
      if (gen !== greetingFetchGenRef.current) return;
      setMessages([{ id: 0, text: String(text).trim(), sender: 'ai' }]);
    } catch {
      if (gen !== greetingFetchGenRef.current) return;
      setMessages([DEFAULT_WELCOME]);
    } finally {
      if (gen === greetingFetchGenRef.current) {
        setGreetingLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (readStoredChat()) {
      return;
    }
    loadFreshGreeting();
  }, [loadFreshGreeting]);

  useEffect(() => {
    if (!messages || greetingLoading) return;
    const persistable = messages.filter((m) => !m.isThinking && !m.isStreaming);
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persistable));
    } catch {
      // sessionStorage unavailable or quota exceeded
    }
  }, [messages, greetingLoading]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, greetingLoading]);

  const handleNewChat = () => {
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      // ignore
    }
    setPendingLogChallenge(null);
    void loadFreshGreeting();
  };

  useEffect(() => {
    if (inputValue.trim()) setInputHint('');
  }, [inputValue]);

  const sendMessage = async () => {
    const trimmed = inputValue.trim();
    if (!trimmed || !messages) {
      setInputHint('Type a question or ask me anything about your Kashé challenges and points.');
      return;
    }

    const affirm = isAffirmativeForPending(trimmed);
    let pendingChallengeTitle = affirm ? getPendingLogChallenge() : null;
    if (!affirm) {
      setPendingLogChallenge(null);
    }

    let aiMessageId;
    setMessages((prev) => {
      const maxId = prev.reduce(
        (m, x) => (typeof x.id === 'number' && x.id > m ? x.id : m),
        -1
      );
      const userId = maxId + 1;
      aiMessageId = maxId + 2;
      return [
        ...prev,
        { id: userId, text: trimmed, sender: 'user' },
        {
          id: aiMessageId,
          text: '',
          sender: 'ai',
          isThinking: true,
          isStreaming: false,
        },
      ];
    });
    setInputValue('');
    setInputHint('');
    setLoading(true);

    const history = messages
      .filter((m) => !m.isThinking && !m.isStreaming)
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'model',
        text: m.text,
      }));

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CHAT_REQUEST_TIMEOUT_MS);

    const beginStreaming = () => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMessageId
            ? { ...m, isThinking: false, isStreaming: true, text: '' }
            : m
        )
      );
    };

    const appendChunk = (chunk) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMessageId ? { ...m, text: (m.text || '') + chunk } : m
        )
      );
    };

    let streamed = false;

    try {
      const token = localStorage.getItem('token');
      const body = {
        message: trimmed,
        history,
        ...(pendingChallengeTitle ? { pending_challenge_title: pendingChallengeTitle } : {}),
      };

      await consumeChatStream({
        body,
        token,
        signal: controller.signal,
        onMeta: (meta) => {
          if (!meta || !('pending_challenge_title' in meta)) return;
          const next = meta.pending_challenge_title;
          if (next && String(next).trim()) {
            setPendingLogChallenge(String(next).trim());
          } else {
            setPendingLogChallenge(null);
          }
        },
        onChunk: (chunk) => {
          if (!streamed) {
            streamed = true;
            beginStreaming();
          }
          appendChunk(chunk);
        },
      });

      if (!streamed) {
        beginStreaming();
      }

      setMessages((prev) => {
        const current = prev.find((m) => m.id === aiMessageId);
        let text = (current?.text || '').trim();
        if (
          text.includes("didn't understand") ||
          text.includes('did not understand') ||
          !text
        ) {
          text = text.replace(/sorry[^.]*\.?\s*/gi, '').trim() || '';
          text = text || KASHE_HELP_FALLBACK_REPLY;
        }
        return prev.map((m) =>
          m.id === aiMessageId
            ? { ...m, text, isThinking: false, isStreaming: false }
            : m
        );
      });
    } catch (err) {
      const abort = err?.name === 'AbortError';
      const text = abort
        ? 'That request took longer than usual. Kashé might be busy — try logging a class by challenge name or check your Challenges tab.'
        : (err.message && String(err.message).trim()) ||
          'Connection issue. Double-check your network and try again.';

      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMessageId
            ? {
                ...m,
                text: `${text}\n\n${KASHE_HELP_FALLBACK_REPLY}`,
                isThinking: false,
                isStreaming: false,
              }
            : m
        )
      );
    } finally {
      clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const showGreetingPlaceholder = greetingLoading && (!messages || messages.length === 0);

  return (
    <div className="chat-container">
      <div className="chat-header">
        <p className="chat-coach-title">Kai · Kashé fitness coach</p>
        <button
          type="button"
          className="chat-new-btn"
          onClick={handleNewChat}
          disabled={greetingLoading}
        >
          New chat
        </button>
      </div>

      <div className="messages-area">
        {showGreetingPlaceholder && (
          <div className="greeting-loading">Getting your update...</div>
        )}
        {!showGreetingPlaceholder &&
          messages &&
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-bubble ${msg.sender} ${
                msg.isThinking ? 'thinking' : ''
              } ${msg.isStreaming ? 'streaming' : ''}`}
            >
              {msg.isThinking ? (
                <span className="thinking-dots">thinking</span>
              ) : (
                <span className="message-text">
                  {msg.text}
                  {msg.isStreaming && <span className="stream-cursor" aria-hidden />}
                </span>
              )}
            </div>
          ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <div className="chat-input-stack">
          {inputHint && <p className="chat-input-hint">{inputHint}</p>}
          <div className="chat-input-row">
            <input
              type="text"
              className="message-input"
              placeholder="Plan my week, check my pace, log a class..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={loading || greetingLoading || !messages}
            />
            <button
              type="button"
              className="send-button"
              onClick={sendMessage}
              disabled={loading || greetingLoading || !messages || !inputValue.trim()}
            >
              Send
            </button>
          </div>
        </div>
      </div>

      <Navbar setIsAuthenticated={setIsAuthenticated} />
    </div>
  );
}

export default Chat;
