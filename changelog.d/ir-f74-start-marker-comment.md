- The hook runtime's start marker explains why it ignores `OSError` (no launcher on fd 9 is not an
  error), clearing CodeQL py/empty-except; behaviour unchanged (IR-F74).
