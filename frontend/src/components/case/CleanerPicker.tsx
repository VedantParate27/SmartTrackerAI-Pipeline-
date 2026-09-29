import { Field } from '#/components/ui'

export interface KnownCleaner {
  id: number
  name: string | null
}

/** A positive integer user id, or null for blank/invalid input. */
export function parseCleanerId(value: string) {
  const id = Number(value.trim())
  return Number.isInteger(id) && id > 0 ? id : null
}

/**
 * There is no cleaner directory endpoint, so the admin types a user id. The
 * suggestions are cleaners seen in past assignment events; any other id is
 * still accepted and the backend answers 400 if that user is not a cleaner.
 */
export default function CleanerPicker({
  id,
  value,
  onChange,
  cleaners,
  error,
  disabled,
  label = 'Cleaner user ID',
}: {
  id: string
  value: string
  onChange: (value: string) => void
  cleaners: KnownCleaner[]
  error?: string
  disabled?: boolean
  label?: string
}) {
  const listId = `${id}-known`
  return (
    <Field
      label={label}
      htmlFor={id}
      error={error}
      hint={
        cleaners.length > 0
          ? `Suggestions come from past assignments (${cleaners.length} known).`
          : 'No cleaners assigned yet — enter the user ID of a cleaner account.'
      }
    >
      <input
        id={id}
        className="input"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        list={listId}
        placeholder="e.g. 3"
        value={value}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id={listId}>
        {cleaners.map((cleaner) => (
          <option key={cleaner.id} value={String(cleaner.id)}>
            {cleaner.name
              ? `#${cleaner.id} · ${cleaner.name}`
              : `#${cleaner.id}`}
          </option>
        ))}
      </datalist>
    </Field>
  )
}
