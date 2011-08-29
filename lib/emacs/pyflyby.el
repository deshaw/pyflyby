
(defun pyflyby-transform-region-with-command (command)
  (unless (eq major-mode 'python-mode)
    (error "Pyflyby should only be used on python buffers"))
  (shell-command-on-region (point-min) (point-max) command
                           nil t "*pyflyby*" t))

(defun pyflyby-tidy-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "tidy-imports"))

(defun pyflyby-reformat-imports ()
  (interactive "*")
  (pyflyby-transform-region-with-command "reformat-imports"))


(defalias 'tidy-imports 'pyflyby-tidy-imports)
(defalias 'reformat-imports 'pyflyby-reformat-imports)

(provide 'pyflyby)
