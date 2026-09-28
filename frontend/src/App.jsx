import React from 'react';
import Dashboard from './pages/Dashboard';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary caught error]:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#F5F5F7] text-[#1D1D1F] flex flex-col items-center justify-center p-6 text-center font-sans antialiased">
          <div className="bg-white border border-[#E5E5E7] p-8 rounded-3xl max-w-md w-full space-y-4 shadow-sm">
            <div className="w-12 h-12 rounded-2xl bg-[#FF3B30]/10 text-[#FF3B30] flex items-center justify-center mx-auto text-xl font-bold">
              !
            </div>
            <h2 className="text-base font-semibold text-[#1D1D1F]">Something went wrong</h2>
            <p className="text-xs text-[#86868B] leading-relaxed">
              {this.state.error?.message || 'An unexpected interface error occurred.'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-5 py-2 rounded-xl bg-[#0071E3] hover:bg-[#0077ED] text-white font-medium text-xs shadow-sm transition-colors cursor-pointer"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <Dashboard />
    </ErrorBoundary>
  );
}

