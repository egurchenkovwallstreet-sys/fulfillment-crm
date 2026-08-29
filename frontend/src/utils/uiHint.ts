/** Подсказка при наведении — для кнопок, ссылок и пунктов меню. */
export function uiHint(text: string) {
  return { 'data-hint': text, title: text } as const
}

/** Обёртка для disabled-кнопок: подсказка срабатывает на span. */
export function hintWrapProps(text: string) {
  return { className: 'hint-wrap', ...uiHint(text) } as const
}
