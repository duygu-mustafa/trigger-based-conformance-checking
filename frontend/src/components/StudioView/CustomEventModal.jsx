import CustomEventBuilder from './CustomEventBuilder'

export default function CustomEventModal({ isOpen, onClose, savedEventTypes, onSave, onDelete }) {
  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Define a custom event type</h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">×</button>
        </div>
        <div className="modal-body">
          <CustomEventBuilder
            savedEventTypes={savedEventTypes}
            onSave={(et) => { onSave(et) }}
            onDelete={onDelete}
          />
        </div>
      </div>
    </div>
  )
}
