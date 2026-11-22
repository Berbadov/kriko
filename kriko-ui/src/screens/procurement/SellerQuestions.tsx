import { useState } from 'react'
import type { EstimateLine, EstimateQuote } from '../../engine/estimates'
import { buildSellerQuestions, mailtoHref, type SellerClaim } from '../../engine/sellerQuestions'
import { downloadFile } from '../../engine/sheet'
import { slug } from './format'
import { ModalDialog } from './ApprovalSheet'

/** The questions to put to the seller before buying one product, in an
 *  editable text. Copy, Download .txt and Open in email all use the text as it
 *  stands. Nothing here asks a person to approve anything: the list is built
 *  from the product's own known problems and its quote, and the reader sends it. */

export function SellerQuestions({ line, quote, claims, claimsReady, onClose }: {
  line: Pick<EstimateLine, 'label'>
  quote: EstimateQuote | null
  claims: SellerClaim[] | undefined
  /** False while the product's known problems are still being read. */
  claimsReady: boolean
  onClose: () => void
}) {
  // Built once when the dialog opens; the reader's edits then belong to the text box.
  const [built] = useState(() => buildSellerQuestions({ line, quote, claims, today: new Date() }))
  const [text, setText] = useState(built.body)
  const [note, setNote] = useState('')
  const link = mailtoHref(built.subject, text)
  const counts = {
    claim: built.items.filter((item) => item.source === 'claim').length,
    quote: built.items.filter((item) => item.source === 'quote').length,
    risk: built.items.filter((item) => item.source === 'risk').length,
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setNote('Copied.')
    } catch {
      setNote('Could not copy here. Select the text instead.')
    }
  }

  const download = () => {
    downloadFile(`${slug(line.label)}-seller-questions.txt`, text, 'text/plain;charset=utf-8')
    setNote('Downloaded.')
  }

  return (
    <ModalDialog label="Questions for the seller" onClose={onClose}>
      <div className="pdialog-body questions">
        <p className="questions-lede">
          {built.items.length} {built.items.length === 1 ? 'question' : 'questions'}: {counts.claim} from the known problems,
          {' '}{counts.quote} from the quote, {counts.risk} from the check of the quote. Edit the text as you like.
        </p>
        {!claimsReady && (
          <p className="k-notice" role="status">The known problems of this product are still being read. Close and open this again to include them.</p>
        )}
        <label className="k-field questions-field">
          <span>Questions for the seller</span>
          <textarea
            className="k-input questions-text"
            rows={16}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <div className="questions-actions">
          <button type="button" className="k-btn" data-kind="quiet" onClick={() => void copy()}>Copy</button>
          <button type="button" className="k-btn" data-kind="quiet" onClick={download}>Download .txt</button>
          <a className="k-btn" data-kind="primary" href={link.href}>Open in email</a>
        </div>
        {link.cut && (
          <p className="questions-small">The email link holds 1800 characters, so it stops early. The full list is in the text box: copy it into the email.</p>
        )}
        {note && <p className="questions-small" role="status">{note}</p>}
      </div>
    </ModalDialog>
  )
}
