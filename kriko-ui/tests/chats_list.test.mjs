import test from 'node:test'
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, unnamedButtons } from './settings_support.mjs'

/**
 * The saved chats, listed above the checks on History. The engine hooks are
 * stubbed: the list is drawn from `threads`, and every press is recorded, so a
 * test reads what the reader was offered and what the component asked the engine to do.
 */

const LIST = 'src/ui/ChatsList.tsx'

const chat = (id, title, extra = {}) => ({ id, title, at: 0, when: '2 hours ago', pinned: false, ...extra })

/** Load the list with the engine stubbed to `threads`, and a record of what it was asked. */
function load({ threads = [], threadId = '' } = {}) {
  const calls = { removed: [], renamed: [], pinned: [], opened: [], newChat: 0 }
  const stubs = {
    '../chat': {
      useChat: () => ({
        threadId,
        newChat: () => calls.newChat++,
        open: async (id) => calls.opened.push(id),
      }),
    },
    '../engine/threads': {
      useThreads: () => ({
        threads,
        problem: '',
        live: true,
        remove: async (id) => calls.removed.push(id),
        rename: async (id, title) => calls.renamed.push([id, title]),
        pin: async (id, pinned) => calls.pinned.push([id, pinned]),
      }),
    },
    '../engine/chatexport': { chatMarkdown: async () => '# Chat' },
    './clipboard': { copyText: async () => true },
  }
  const ChatsList = loadSource(LIST, stubs).ChatsList
  return { ChatsList, calls }
}

const byText = (document, text) => [...document.querySelectorAll('button')].find((button) => button.textContent.trim() === text)

test('pinned chats are listed first, under their own caption', async () => {
  const { ChatsList } = load({
    threads: [chat('kettle', 'Is the kettle safe?'), chat('drill', 'Which drill lasts?', { pinned: true })],
  })
  const document = domOf(renderToStaticMarkup(h(ChatsList, { onOpen() {} })))
  const groups = [...document.querySelectorAll('.chats-group')]
  assert.deepEqual(groups.map((group) => group.getAttribute('aria-label')), ['Pinned', 'Recent'])
  assert.equal(groups[0].querySelector('.k-row-title').textContent, 'Which drill lasts?')
  assert.equal(groups[1].querySelector('.k-row-title').textContent, 'Is the kettle safe?')
})

test('the open chat is marked with aria-current, and nothing else is', async () => {
  const { ChatsList } = load({ threads: [chat('kettle', 'Is the kettle safe?'), chat('drill', 'Which drill lasts?')], threadId: 'drill' })
  const document = domOf(renderToStaticMarkup(h(ChatsList, { onOpen() {} })))
  const current = [...document.querySelectorAll('[aria-current="true"]')]
  assert.deepEqual(current.map((node) => node.querySelector('.k-row-title').textContent), ['Which drill lasts?'])
})

test('the block draws nothing when there are no chats and no search', async () => {
  const { ChatsList } = load({ threads: [] })
  assert.equal(renderToStaticMarkup(h(ChatsList, { onOpen() {} })), '')
})

test('every control in the list carries a name, opened or closed', async () => {
  const { ChatsList } = load({ threads: [chat('kettle', 'Is the kettle safe?', { pinned: true }), chat('drill', 'Which drill lasts?')] })
  const view = await mount(h(ChatsList, { onOpen() {} }))
  try {
    assert.deepEqual(unnamedButtons(view.document), [], 'closed rows')
    await view.click(view.document.querySelector('[aria-label="More for Is the kettle safe?"]'))
    assert.deepEqual(unnamedButtons(view.document), [], 'a row with its actions open')
    const words = [...view.document.querySelectorAll('.chats-acts button')].map((button) => button.textContent.trim())
    assert.deepEqual(words, ['Open', 'Unpin', 'Rename', 'Copy as Markdown', 'Delete'])
  } finally {
    await view.unmount()
  }
})

test('delete asks in words before it deletes, and Keep leaves the chat alone', async () => {
  const { ChatsList, calls } = load({ threads: [chat('kettle', 'Is the kettle safe?')] })
  const view = await mount(h(ChatsList, { onOpen() {} }))
  try {
    await view.click(view.document.querySelector('[aria-label="More for Is the kettle safe?"]'))
    await view.click(view.document.querySelector('[aria-label="Delete Is the kettle safe?"]'))
    assert.deepEqual(calls.removed, [], 'nothing is deleted by the first press')
    const ask = view.document.querySelector('.chats-ask')
    assert.ok(ask, 'the confirm is drawn inline')
    assert.match(ask.textContent, /Delete this chat\?/)

    await view.click(byText(view.document, 'Keep'))
    assert.deepEqual(calls.removed, [], 'Keep deletes nothing')
    assert.equal(view.document.querySelector('.chats-ask'), null, 'the confirm closes')

    await view.click(view.document.querySelector('[aria-label="More for Is the kettle safe?"]'))
    await view.click(view.document.querySelector('[aria-label="Delete Is the kettle safe?"]'))
    await view.click(view.document.querySelector('.chats-ask .k-btn[data-kind="danger"]'))
    assert.deepEqual(calls.removed, ['kettle'], 'the second press, on Delete, removes the chat')
  } finally {
    await view.unmount()
  }
})

test('opening a chat asks the engine for it and tells the page to show the Ask screen', async () => {
  const opened = []
  const { ChatsList, calls } = load({ threads: [chat('kettle', 'Is the kettle safe?')] })
  const view = await mount(h(ChatsList, { onOpen: (id) => opened.push(id) }))
  try {
    await view.click(view.document.querySelector('.chats-open'))
    assert.deepEqual(calls.opened, ['kettle'])
    assert.deepEqual(opened, ['kettle'])
  } finally {
    await view.unmount()
  }
})
