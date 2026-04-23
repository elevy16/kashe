import { useState, useEffect, useRef } from 'react';
import Navbar from '../components/Navbar';
import './Chat.css';

function Chat() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      text: "Hi! I'm your Kashé coach. Ask me about your points, challenges, or anything fitness related!",
      sender: 'ai',
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!inputValue.trim()) return;

    // Add user message immediately
    const userMessage = {
      id: messages.length,
      text: inputValue,
      sender: 'user',
    };
    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');

    // Show thinking bubble
    const thinkingMessage = {
      id: messages.length + 1,
      text: 'thinking...',
      sender: 'ai',
      isThinking: true,
    };
    setMessages((prev) => [...prev, thinkingMessage]);
    setLoading(true);

    try {
      const token = localStorage.getItem('token');
      const response = await fetch('http://127.0.0.1:5000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ message: inputValue }),
      });

      if (!response.ok) {
        throw new Error('Failed to get response');
      }

      const data = await response.json();

      // Replace thinking message with AI response
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          id: updated.length,
          text: data.reply || "I'm sorry, I didn't understand that. Please try again.",
          sender: 'ai',
          isThinking: false,
        };
        return updated;
      });
    } catch (err) {
      // Replace thinking message with error
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          id: updated.length,
          text: "Sorry, I encountered an error. Please try again.",
          sender: 'ai',
          isThinking: false,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="chat-container">
      <div className="messages-area">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`message-bubble ${msg.sender} ${
              msg.isThinking ? 'thinking' : ''
            }`}
          >
            {msg.text}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <input
          type="text"
          className="message-input"
          placeholder="Ask me anything..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          disabled={loading}
        />
        <button
          className="send-button"
          onClick={sendMessage}
          disabled={loading || !inputValue.trim()}
        >
          Send
        </button>
      </div>

      <Navbar />
    </div>
  );
}

export default Chat;