import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = {
  children: ReactNode
}

type State = {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[CRM] UI crash:', error, info.componentStack)
  }

  private handleReload = () => {
    window.location.reload()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="error-boundary">
        <h2>Ошибка интерфейса</h2>
        <p className="error-boundary__message">{error.message}</p>
        <p className="error-boundary__hint">
          Частые причины: автоперевод Chrome (закройте панель «Перевести»), расширения браузера.
          Ярлык CRM: <code>--disable-extensions --kiosk-printing</code>.
        </p>
        <button type="button" className="btn btn--primary" onClick={this.handleReload}>
          Обновить страницу
        </button>
      </div>
    )
  }
}
