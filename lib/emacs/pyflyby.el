
(defun pyflyby-transform-region-with-command (command &rest args)
  (unless (eq major-mode 'python-mode)
    (error "Pyflyby should only be used on python buffers"))
  (let* ((output-buffer (generate-new-buffer "*pyflyby output*"))
         (exit-value (apply 'call-process-region
                            (point-min) (point-max) command nil
                            (list output-buffer "*pyflyby log*")
                            nil args)))
    (if (= exit-value 0)
        ;; Process exited successfully.
        (let ((newtext
               (with-current-buffer output-buffer
                 (buffer-substring-no-properties (point-min) (point-max)))))
          (if (string= newtext
                       (buffer-substring-no-properties (point-min) (point-max)))
              ;; No change.
              (message "No changes by `%s'" command)
            ;; There were changes.
            (let* ((p (point))
                   (ptext (buffer-substring-no-properties
                           p (min (point-max) (+ p 1000))))
                   (size (buffer-size)))
              ;; Replace the buffer.
              (erase-buffer)
              (insert newtext)
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
              (recenter))))
      ;; Process failed.
      (error "%s failed with exit code %d" command exit-value))
    (kill-buffer output-buffer)))


(defun pyflyby-tidy-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "tidy-imports"))

(defun pyflyby-reformat-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "reformat-imports"))


(defalias 'tidy-imports 'pyflyby-tidy-imports)
(defalias 'reformat-imports 'pyflyby-reformat-imports)

(provide 'pyflyby)
