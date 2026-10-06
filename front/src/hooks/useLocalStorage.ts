// localStorage 에 저장되는 상태. 저장소를 쓸 수 없어도 메모리 상태로 정상 동작한다 (구현지시서 9.2절).
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { readJson, writeJson } from '../lib/storage';

/**
 * @param parse 저장된 값을 검사·정리한다. 모양이 틀리면 undefined 를 돌려 초기값을 쓰게 한다.
 */
export function useLocalStorage<T>(key: string, initial: T, parse: (raw: unknown) => T | undefined): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    const raw = readJson(key);
    return raw === undefined ? initial : (parse(raw) ?? initial);
  });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false; // 처음 읽은 값을 그대로 다시 쓰지 않는다
      return;
    }
    writeJson(key, value);
  }, [key, value]);
  return [value, setValue];
}
