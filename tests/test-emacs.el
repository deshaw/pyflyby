(require 'ert)
(require 'pyflyby)

(ert-deftest pyflyby-loads-correctly ()
  "Ensure pyflyby.el loads without errors."
  (should (featurep 'pyflyby)))

(ert-deftest pyflyby-tidy-imports-works ()
  (with-temp-buffer
    (insert "import os, sys\nprint(os.getcwd())\n")
    (python-mode)
    (pyflyby-tidy-imports)
    (should (string=
             (buffer-string)
             (concat
              "from __future__ import print_function\n\n"
              "import os\n"
              "print(os.getcwd())\n")))) )
