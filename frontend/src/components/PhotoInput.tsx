import { useEffect, useState } from 'react'
import { IMAGE_TYPES, MAX_IMAGE_BYTES } from '#/lib/api'

/**
 * Client-side mirror of backend/image_utils.py. The backend still sniffs the
 * bytes and answers 422 with a code on anything this misses (e.g. a renamed
 * file), which api.ts translates.
 */
function checkPhoto(file: File) {
  if (file.size === 0) return 'That file is empty. Choose another photo.'
  if (!(IMAGE_TYPES as ReadonlyArray<string>).includes(file.type)) {
    return 'Only JPEG, PNG or WebP photos are accepted.'
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return 'That photo is over 8 MB. Choose a smaller one.'
  }
  return null
}

/**
 * Photo picker with preview. Controlled: the parent owns the chosen file and
 * clears it (null) after a successful upload. `capture` opens the camera
 * straight away on phones — and hides the gallery — so only cleanup proofs,
 * which must be taken on site, ask for it.
 */
export default function PhotoInput({
  id,
  file,
  onChange,
  disabled,
  title = 'Take or choose a photo',
  hint,
  error,
  capture,
}: {
  id: string
  file: File | null
  onChange: (file: File | null) => void
  disabled?: boolean
  title?: string
  hint?: string
  /** An upload error from the parent, shown under the picker. */
  error?: string | null
  capture?: 'environment'
}) {
  const [problem, setProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)

  // The preview follows the chosen file; its object URL is always released.
  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const message = problem ?? error ?? null

  return (
    <div className="grid gap-2">
      <label className="file-drop relative" htmlFor={id}>
        <input
          id={id}
          type="file"
          accept={IMAGE_TYPES.join(',')}
          capture={capture}
          disabled={disabled}
          aria-invalid={Boolean(message)}
          aria-describedby={message ? `${id}-error` : undefined}
          onChange={(event) => {
            const next = event.target.files?.[0] ?? null
            // Let the same file be picked again after a removal.
            event.target.value = ''
            if (!next) return
            const found = checkPhoto(next)
            setProblem(found)
            onChange(found ? null : next)
          }}
        />
        {preview ? (
          <img className="file-preview" src={preview} alt="Selected photo" />
        ) : (
          <span aria-hidden="true" className="file-drop-icon">
            <svg
              viewBox="0 0 24 24"
              width="22"
              height="22"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.6l1.4-2h5l1.4 2h1.6A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5Z" />
              <circle cx="12" cy="12.5" r="3.5" />
            </svg>
          </span>
        )}
        <span className="max-w-full font-bold text-(--fg) [overflow-wrap:anywhere]">
          {file ? file.name : title}
        </span>
        <span>{hint ?? 'JPEG, PNG or WebP · up to 8 MB'}</span>
      </label>

      {file ? (
        <div>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            disabled={disabled}
            onClick={() => {
              setProblem(null)
              onChange(null)
            }}
          >
            Remove photo
          </button>
        </div>
      ) : null}

      {message ? (
        <p className="field-error m-0" id={`${id}-error`}>
          <span aria-hidden="true">!</span>
          <span>{message}</span>
        </p>
      ) : null}
    </div>
  )
}
