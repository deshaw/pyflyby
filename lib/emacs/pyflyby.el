
(defun pyflyby-transform-region-with-command (command)
  (unless (eq major-mode 'python-mode)
    (error "Pyflyby should only be used on python buffers"))
  (let* ((p (point))
         (text (buffer-substring-no-properties p (min (point-max) (+ p 1000))))
         (size (buffer-size)))
    (shell-command-on-region (point-min) (point-max) command
                             nil t "*pyflyby*" t)
    ;; Go to previously saved point.  We don't use save-excursion since that
    ;; doesn't work when the whole buffer is replaced, destroying markers.
    ;; First see if the position matches when counting from end of the buffer.
    (setq p (+ p (buffer-size) (- size)))
    (goto-char p)
    (unless (search-forward text (+ p 1) t)
      ;; Next try searching for the location based on text near old point.
      (goto-char (- p 500))
      (if (search-forward text (+ p 1000) t)
          (goto-char (match-beginning 0))
        (goto-char p)))
    (recenter)))


(defun pyflyby-tidy-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "tidy-imports"))

(defun pyflyby-reformat-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "reformat-imports"))


(defalias 'tidy-imports 'pyflyby-tidy-imports)
(defalias 'reformat-imports 'pyflyby-reformat-imports)

(provide 'pyflyby)
