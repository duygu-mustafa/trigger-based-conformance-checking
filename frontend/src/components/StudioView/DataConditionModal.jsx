import DataConditionBuilder from './DataConditionBuilder'

export default function DataConditionModal({ isOpen, onClose, savedConditions, onSave, onDelete, itemOptions }) {
  if (!isOpen) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Define a data condition</h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">×</button>
        </div>
        <div className="modal-body">
          <DataConditionBuilder
            savedConditions={savedConditions}
            onSave={cond => { onSave(cond) }}
            onDelete={onDelete}
            itemOptions={itemOptions}
          />
        </div>
      </div>
    </div>
  )
}
