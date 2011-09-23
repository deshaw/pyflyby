
(defun pyflyby--pipe-to-command (start end program &rest args)
  "Send text from START to END to process running PROGRAM ARGS.

Returns (exit-value stdout stderr)."
  ;; Yuck: call-process-region can only redirect stderr to a file, not to a
  ;; buffer/string.
  (let* ((stdout-buffer (generate-new-buffer " *pyflyby stdout*"))
         (stderr-buffer (generate-new-buffer " *pyflyby stderr*"))
         (stderr-file (make-temp-file
                       (expand-file-name
                        "pyflyby-log."
                        (or small-temporary-file-directory
                            temporary-file-directory))))
         (exit-value (apply 'call-process-region
                            start end program nil
                            (list stdout-buffer stderr-file)
                            nil args))
         (stdout-text (with-current-buffer stdout-buffer (buffer-string)))
         (stderr-text (with-current-buffer stderr-buffer
                        (format-insert-file stderr-file nil)
                        (buffer-string))))
    (delete-file stderr-file)
    (kill-buffer stdout-buffer)
    (kill-buffer stderr-buffer)
    (list exit-value stdout-text stderr-text)))


(defun pyflyby--replace-text (text)
  "Replace current buffer with TEXT.

Tries to keep point in the same place."
  (let* ((p (point))
         (ptext (buffer-substring-no-properties
                 p (min (point-max) (+ p 1000))))
         (size (buffer-size)))
    ;; Replace the buffer.
    (erase-buffer)
    (insert text)
    ;; Go to previously saved point.  We don't use save-excursion
    ;; since that doesn't work when the whole buffer is replaced,
    ;; destroying markers.  First see if the position matches when
    ;; counting from end of the buffer.
    (setq p (+ p (buffer-size) (- size)))
    (goto-char p)
    (unless (search-forward ptext (+ p 1) t)
      ;; Next, try searching for the location based on text near old
      ;; point.
      (goto-char (- p 500))
      (if (search-forward ptext (+ p 1000) t)
          (goto-char (match-beginning 0))
        (goto-char p)))
    (recenter)))


(defun pyflyby-transform-region-with-command (command &rest args)
  (unless (eq major-mode 'python-mode)
    (error "Pyflyby should only be used on python buffers"))
  (let* ((result
          (apply 'pyflyby--pipe-to-command (point-min) (point-max) command args))
         (exit-value (nth 0 result))
         (newtext (nth 1 result))
         (logtext (nth 2 result))
         (nlogtext (if (= 0 (length logtext)) "" (concat "\n" logtext))))
    (if (= exit-value 0)
        ;; Process exited successfully.
        (if (string= newtext
                     (buffer-substring-no-properties (point-min) (point-max)))
            ;; No change.
            (message "No changes by `%s'.%s" command nlogtext)
          ;; There were changes.
          (pyflyby--replace-text newtext)
          (message logtext))
      ;; Process failed.
      (error "%s failed with exit code %d.%s" command exit-value logtext))))


(defun pyflyby-tidy-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "tidy-imports"))

(defun pyflyby-reformat-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "reformat-imports"))


(defalias 'tidy-imports 'pyflyby-tidy-imports)
(defalias 'reformat-imports 'pyflyby-reformat-imports)

(provide 'pyflyby)
