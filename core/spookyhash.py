"""Implémentation autonome en pur Python de SpookyHash V2 (Bob Jenkins, 2012).

Permet d'utiliser SpookyHash sans aucune installation de module C ou pip.
Fournit une empreinte 128-bit haute performance avec d'excellentes propriétés d'avalanche.
"""

from typing import Union

# Constante de SpookyHash
SC_CONST = 0xDEADBEEFDEADBEEF
MASK64 = 0xFFFFFFFFFFFFFFFF


def _rot64(x: int, k: int) -> int:
    return (((x << k) & MASK64) | ((x & MASK64) >> (64 - k))) & MASK64


class SpookyHashV2:
    """Calculateur SpookyHash V2 (128-bit).
    
    Supporte l'alimentation incrémentale par blocs (streaming) via update()
    et la finalisation via hexdigest() / digest().
    """

    def __init__(self, seed1: int = 0, seed2: int = 0):
        self.seed1 = seed1 & MASK64
        self.seed2 = seed2 & MASK64
        self.reset()

    def reset(self):
        """Réinitialise l'état interne pour un nouveau calcul."""
        self.length = 0
        self.remainder = bytearray()
        # État interne de 12 entiers de 64 bits
        self.h = [SC_CONST] * 12
        self.h[0] = self.seed1
        self.h[1] = self.seed2

    def _mix(self):
        h = self.h
        h[0] = (h[0] + h[3]) & MASK64; h[10] = _rot64(h[10] ^ h[0], 11)
        h[1] = (h[1] + h[4]) & MASK64; h[11] = _rot64(h[11] ^ h[1], 32)
        h[2] = (h[2] + h[5]) & MASK64; h[0] = _rot64(h[0] ^ h[2], 43)
        h[3] = (h[3] + h[6]) & MASK64; h[1] = _rot64(h[1] ^ h[3], 31)
        h[4] = (h[4] + h[7]) & MASK64; h[2] = _rot64(h[2] ^ h[4], 17)
        h[5] = (h[5] + h[8]) & MASK64; h[3] = _rot64(h[3] ^ h[5], 28)
        h[6] = (h[6] + h[9]) & MASK64; h[4] = _rot64(h[4] ^ h[6], 39)
        h[7] = (h[7] + h[10]) & MASK64; h[5] = _rot64(h[5] ^ h[7], 57)
        h[8] = (h[8] + h[11]) & MASK64; h[6] = _rot64(h[6] ^ h[8], 55)
        h[9] = (h[9] + h[0]) & MASK64; h[7] = _rot64(h[7] ^ h[9], 54)
        h[10] = (h[10] + h[1]) & MASK64; h[8] = _rot64(h[8] ^ h[10], 22)
        h[11] = (h[11] + h[2]) & MASK64; h[9] = _rot64(h[9] ^ h[11], 46)

    def _end_partial(self):
        h = self.h
        h[11] = (h[11] + h[1]) & MASK64; h[2] = _rot64(h[2] ^ h[11], 44)
        h[0] = (h[0] + h[2]) & MASK64; h[3] = _rot64(h[3] ^ h[0], 15)
        h[1] = (h[1] + h[3]) & MASK64; h[4] = _rot64(h[4] ^ h[1], 34)
        h[2] = (h[2] + h[4]) & MASK64; h[5] = _rot64(h[5] ^ h[2], 21)
        h[3] = (h[3] + h[5]) & MASK64; h[6] = _rot64(h[6] ^ h[3], 38)
        h[4] = (h[4] + h[6]) & MASK64; h[7] = _rot64(h[7] ^ h[4], 33)
        h[5] = (h[5] + h[7]) & MASK64; h[8] = _rot64(h[8] ^ h[5], 10)
        h[6] = (h[6] + h[8]) & MASK64; h[9] = _rot64(h[9] ^ h[6], 13)
        h[7] = (h[7] + h[9]) & MASK64; h[10] = _rot64(h[10] ^ h[7], 38)
        h[8] = (h[8] + h[10]) & MASK64; h[11] = _rot64(h[11] ^ h[8], 53)
        h[9] = (h[9] + h[11]) & MASK64; h[0] = _rot64(h[0] ^ h[9], 42)
        h[10] = (h[10] + h[0]) & MASK64; h[1] = _rot64(h[1] ^ h[10], 54)

    def _end(self):
        self._end_partial()
        self._end_partial()
        self._end_partial()

    def update(self, data: Union[bytes, bytearray, memoryview]):
        """Met à jour le hash avec un nouveau bloc de données (streaming)."""
        if not data:
            return

        self.length += len(data)
        self.remainder.extend(data)

        # Taille d'un bloc de SpookyHash : 96 octets (12 entiers de 64 bits)
        block_size = 96
        while len(self.remainder) >= block_size:
            chunk = self.remainder[:block_size]
            del self.remainder[:block_size]

            # Ingestion des 12 mots de 64 bits en little-endian
            for i in range(12):
                offset = i * 8
                val = int.from_bytes(chunk[offset:offset + 8], "little")
                self.h[i] = (self.h[i] + val) & MASK64

            self._mix()

    def digest(self) -> bytes:
        """Renvoie l'empreinte sous forme d'octets bruts (16 octets / 128 bits)."""
        # Traitement du reste final
        rem = bytearray(self.remainder)
        remainder_len = len(rem)

        # Remplissage du reste jusqu'à un multiple de 8 octets
        pad = (8 - (remainder_len % 8)) % 8
        rem.extend(b"\x00" * pad)

        # Remplissage des blocs non complets avec zéros jusqu'à 96 octets
        if len(rem) < 96:
            rem.extend(b"\x00" * (96 - len(rem)))

        # Ingestion du dernier bloc
        for i in range(12):
            offset = i * 8
            val = int.from_bytes(rem[offset:offset + 8], "little")
            self.h[i] = (self.h[i] + val) & MASK64

        # Le dernier entier reçoit la longueur du reste résiduel
        self.h[11] = (self.h[11] + (remainder_len << 56)) & MASK64

        self._end()

        # Le hash final 128 bits est composé de h[0] et h[1]
        out1 = self.h[0].to_bytes(8, "little")
        out2 = self.h[1].to_bytes(8, "little")
        return out1 + out2

    def hexdigest(self) -> str:
        """Renvoie l'empreinte au format chaîne hexadécimale (32 caractères)."""
        return self.digest().hex()


def spookyhash128(data: bytes, seed1: int = 0, seed2: int = 0) -> str:
    """Fonction utilitaire pour calculer le hash SpookyHash V2 en un seul appel."""
    hasher = SpookyHashV2(seed1, seed2)
    hasher.update(data)
    return hasher.hexdigest()
