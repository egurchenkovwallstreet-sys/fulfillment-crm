import { Link, useLocation } from 'react-router-dom'
import { XlIntakePage } from './XlIntakePage'
import { XlListIntakePanel } from './XlListIntakePanel'
import './XlIntakePage.css'

export function XlIntakeHub() {
  const { pathname } = useLocation()
  const listMode = pathname.startsWith('/intake-xl/list')

  return (
    <>
      <nav className="xl-mode-tabs" aria-label="Режим XL-приёмки">
        <Link
          to="/intake-xl"
          className={`xl-mode-tabs__tab${listMode ? '' : ' xl-mode-tabs__tab--active'}`}
        >
          Приёмка с ячейками
        </Link>
        <Link
          to="/intake-xl/list"
          className={`xl-mode-tabs__tab${listMode ? ' xl-mode-tabs__tab--active' : ''}`}
        >
          Список в Excel
        </Link>
      </nav>
      {listMode ? <XlListIntakePanel /> : <XlIntakePage />}
    </>
  )
}
